"""Strict local profile loader; environment is scoped and never mutated."""

from dataclasses import dataclass, field, fields
import os
from pathlib import Path

from dotenv import dotenv_values
import yaml

from .budget import BudgetSettings
from .execution import ExecutionSettings
from .tool_schemas import TOOLS


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = ROOT / 'profiles/arcbench-app/config.yaml'


@dataclass(frozen=True)
class ModelSettings:
    model: str = 'deepseek-flash'
    base_url: str = 'https://api.arc-bench.com/v1'
    api_key: str = field(default='', repr=False)
    reasoning: str = 'low'
    max_output_tokens: int = 16384
    timeout_seconds: int = 120
    max_retries: int = 2
    prompt_cache_key: str = ''


@dataclass(frozen=True)
class AcceptanceSettings:
    external_tests: bool = True     # Use input/tests/*.spec.ts when the task provides them.
    generate: bool = True           # Generate checks only for scenarios without an independent test.
    max_generated_scenarios: int = 40
    visual: str = 'report'          # off | report | require
    visual_threshold: float = 0.6
    test_timeout_seconds: int = 30
    suite_timeout_seconds: int = 900
    startup_timeout_seconds: int = 90
    clean_install: bool = False     # True reinstalls dependencies for the delivery validation.
    workers: int = 1                # Parallel Playwright workers, as external evaluators run their tests.


@dataclass(frozen=True)
class Profile:
    name: str
    llm: ModelSettings
    vision: ModelSettings  # Retained settings; image tools are a later delivery.
    tools: tuple[str, ...]
    role: str
    workflow: str
    max_requests: int
    max_context_bytes: int
    max_tools_per_response: int
    source: Path
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    image_mode: str = 'disabled'
    compact_ratio: float = 0.8
    observation_chars: int = 12000
    budget: BudgetSettings = field(default_factory=BudgetSettings)
    acceptance: AcceptanceSettings = field(default_factory=AcceptanceSettings)
    skills: tuple[tuple[str, str], ...] = ()  # Optional guidance, read on demand (step 24 variant).
    # Obsolete observations are replaced once this many bytes can be reclaimed at once; 0 disables.
    prune_min_bytes: int = 24000
    # Tool batches whose observations stay complete; older ones are masked. 0 disables.
    observation_window: int = 0


def _keys(data, allowed, label):
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise ValueError(f'Invalid {label} keys (allowed: {", ".join(sorted(allowed))})')


def _positive(value, name, *, zero=False):
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f'{name} must be a {"nonnegative" if zero else "positive"} integer')
    return value


def _settings(data):
    _keys(data, {f.name for f in fields(ModelSettings)}, 'model settings')
    cfg = {**vars(ModelSettings()), **data}
    for key in ('model', 'base_url', 'reasoning', 'api_key', 'prompt_cache_key'):
        if not isinstance(cfg[key], str) or (key not in {'api_key', 'prompt_cache_key'} and not cfg[key].strip()):
            raise ValueError(f'Invalid {key}')
    if cfg['reasoning'] not in {'provider', 'auto', 'none', 'low', 'medium', 'high', 'max'}:
        raise ValueError('Unsupported reasoning setting')
    if not cfg['base_url'].startswith(('http://', 'https://')):
        raise ValueError('base_url must be an HTTP(S) endpoint')
    for key in ('max_output_tokens', 'timeout_seconds', 'max_retries'):
        cfg[key] = _positive(cfg[key], key, zero=key == 'max_retries')
    return ModelSettings(**cfg)


def _instruction(directory, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('Instruction path must be a relative filename')
    path = directory / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Instruction path escapes profile directory')
    return path.read_text(encoding='utf-8-sig').strip()


def _document(path, depth=0):
    """A variant profile states only its differences: `extends` names its base in the
    same directory; sections are merged one level deep and `tools_add` extends the tool list."""
    data = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('A profile is a YAML mapping')
    parent = data.pop('extends', None)
    added = data.pop('tools_add', [])
    if parent is not None:
        if depth > 3 or not isinstance(parent, str) or Path(parent).name != parent:
            raise ValueError('extends names one profile file in the same directory')
        base = _document(path.parent / parent, depth + 1)
        for key, value in data.items():
            base[key] = {**base[key], **value} if isinstance(value, dict) and isinstance(base.get(key), dict) else value
        data = base
    if added:
        if not isinstance(added, list) or not isinstance(data.get('tools'), list):
            raise ValueError('tools_add extends an existing tools list')
        data['tools'] = [*data['tools'], *added]
    return data


def load_profile(path=DEFAULT_PROFILE, *, env_file=None, environment=None, overrides=None):
    """Priority: explicit model overrides > process env > explicit .env > YAML defaults.

    No implicit .env discovery. Empty process values mask file values (including keys).
    """
    path = Path(path).resolve()
    data = _document(path)
    _keys(data, {'name', 'llm', 'tools', 'instructions', 'loop', 'capabilities', 'execution', 'image_mode',
        'budget', 'acceptance', 'skills'}, 'profile')
    _keys(data.get('llm', {}), {f.name for f in fields(ModelSettings)} - {'api_key'}, 'llm')
    instructions = data.get('instructions', {})
    _keys(instructions, {'role', 'workflow'}, 'instructions')
    loop = data.get('loop', {})
    _keys(loop, {'max_requests', 'max_context_bytes', 'max_tools_per_response', 'compact_ratio', 'observation_chars',
        'prune_min_bytes', 'observation_window'}, 'loop')
    capabilities = data.get('capabilities', {})
    _keys(capabilities, {'native_tools', 'streaming', 'images', 'prompt_cache'}, 'capabilities')
    if any(type(v) is not bool for v in capabilities.values()):
        raise ValueError('Capabilities must be booleans')
    if capabilities.get('native_tools') is not True:
        raise ValueError('This engine requires native function tools')
    if capabilities.get('streaming', False):
        raise ValueError('Streaming is not implemented')
    image_mode = data.get('image_mode', 'disabled')
    if image_mode not in {'disabled', 'native', 'fallback'} or capabilities.get('images', False) != (image_mode != 'disabled'):
        raise ValueError('images capability must match image_mode: disabled/native/fallback')
    tools = data.get('tools')
    if not isinstance(tools, list) or not tools or any(not isinstance(t, str) for t in tools):
        raise ValueError('tools must be a nonempty list of names')
    if len(set(tools)) != len(tools) or set(tools) - TOOLS.keys():
        raise ValueError('Profile contains duplicate or unavailable tools')
    values = dict(dotenv_values(env_file, encoding='utf-8-sig', interpolate=False)) if env_file else {}
    values.update(os.environ if environment is None else environment)
    mapping = {'MODEL': 'model', 'OPENAI_BASE_URL': 'base_url', 'OPENAI_API_KEY': 'api_key',
        'MODEL_REASONING': 'reasoning', 'MAX_OUTPUT_TOKENS': 'max_output_tokens'}
    cfg = dict(data.get('llm', {}))
    cfg.update({key: values[name] for name, key in mapping.items() if name in values})
    explicit = overrides or {}
    _keys(explicit, {f.name for f in fields(ModelSettings)}, 'overrides')
    cfg.update(explicit)
    llm = _settings(cfg)
    if capabilities.get('prompt_cache', False) != bool(llm.prompt_cache_key):
        raise ValueError('Explicit prompt cache requires capability=true and a provider-supported prompt_cache_key')
    visual = vars(llm).copy()
    visual.update({key: values[name] for name, key in {'VISUAL_MODEL': 'model',
        'VISUAL_BASE_URL': 'base_url', 'VISUAL_API_KEY': 'api_key', 'VISUAL_REASONING': 'reasoning'}.items()
        if values.get(name)})
    name = data.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Profile name is required')
    execution = dict(data.get('execution', {}))
    _keys(execution, {f.name for f in fields(ExecutionSettings)}, 'execution')
    execution = {**vars(ExecutionSettings()), **execution}
    if execution['backend'] not in {'auto', 'bubblewrap', 'docker', 'host'} or type(execution['network']) is not bool:
        raise ValueError('Execution needs auto/bubblewrap/docker/host and an explicit boolean network policy')
    for key in ('timeout_seconds', 'memory_mb', 'cpus', 'pids', 'tmp_mb', 'max_output_bytes'):
        execution[key] = _positive(execution[key], key)
    for key in ('docker_image', 'docker_user'):
        if not isinstance(execution[key], str) or not execution[key].strip():
            raise ValueError(f'Invalid {key}')
    user = execution['docker_user'].split(':')
    if any(not p.isdecimal() or int(p) == 0 for p in user) or len(user) != 2:
        raise ValueError('docker_user requires a non-root numeric uid:gid')
    ports = execution['allowed_ports']
    if not isinstance(ports, (list, tuple)) or len(set(ports)) != len(ports) or any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
        raise ValueError('allowed_ports must contain unique TCP port numbers')
    execution['allowed_ports'] = tuple(ports)
    port = execution['verification_port']
    if type(port) is not int or not 1 <= port <= 65535 or port in execution['allowed_ports']:
        raise ValueError('verification_port must be a TCP port distinct from allowed_ports')
    ratio = loop.get('compact_ratio', 0.8)
    if type(ratio) not in {int, float} or not 0.25 <= ratio <= 0.95:
        raise ValueError('compact_ratio must be between 0.25 and 0.95')
    skills = data.get('skills', [])
    if not isinstance(skills, list) or any(not isinstance(s, str) or not s.replace('-', '').isalnum() for s in skills) \
            or len(set(skills)) != len(skills):
        raise ValueError('skills is a list of distinct skill names')
    if bool(skills) != ('read_skill' in tools):
        raise ValueError('skills and the read_skill tool are enabled together')
    skills = tuple((name, _instruction(path.parent, f'skills/{name}.md')) for name in skills)
    budget = dict(data.get('budget', {}))
    _keys(budget, {f.name for f in fields(BudgetSettings)}, 'budget')
    # 0 is "no limit" for every limit that grows with the size of the application.
    budget = {key: _positive(value, key, zero=key in {'wall_seconds', 'max_tool_calls', 'max_reported_tokens',
            'max_verification_rounds'})
        for key, value in {**vars(BudgetSettings()), **budget}.items()}
    if budget['wall_seconds'] and budget['verification_reserve_seconds'] >= budget['wall_seconds']:
        raise ValueError('verification_reserve_seconds must be smaller than wall_seconds')
    acceptance = dict(data.get('acceptance', {}))
    _keys(acceptance, {f.name for f in fields(AcceptanceSettings)}, 'acceptance')
    acceptance = {**vars(AcceptanceSettings()), **acceptance}
    if any(type(acceptance[key]) is not bool for key in ('external_tests', 'generate', 'clean_install')):
        raise ValueError('acceptance external_tests/generate/clean_install must be booleans')
    if acceptance['visual'] not in {'off', 'report', 'require'}:
        raise ValueError('acceptance.visual must be off, report or require')
    if type(acceptance['visual_threshold']) not in {int, float} or not 0 < acceptance['visual_threshold'] < 1:
        raise ValueError('acceptance.visual_threshold must be between 0 and 1')
    for key in ('test_timeout_seconds', 'suite_timeout_seconds', 'startup_timeout_seconds', 'workers'):
        acceptance[key] = _positive(acceptance[key], key)
    acceptance['max_generated_scenarios'] = _positive(acceptance['max_generated_scenarios'],
        'max_generated_scenarios', zero=True)
    return Profile(name, llm, _settings(visual), tuple(tools),
        _instruction(path.parent, instructions.get('role')),
        _instruction(path.parent, instructions.get('workflow')),
        _positive(loop.get('max_requests', 40), 'max_requests', zero=True),
        _positive(loop.get('max_context_bytes', 400000), 'max_context_bytes'),
        _positive(loop.get('max_tools_per_response', 16), 'max_tools_per_response'), path,
        ExecutionSettings(**execution), image_mode, ratio,
        _positive(loop.get('observation_chars', 12000), 'observation_chars'),
        BudgetSettings(**budget), AcceptanceSettings(**acceptance), skills,
        _positive(loop.get('prune_min_bytes', 24000), 'prune_min_bytes', zero=True),
        _positive(loop.get('observation_window', 0), 'observation_window', zero=True))
