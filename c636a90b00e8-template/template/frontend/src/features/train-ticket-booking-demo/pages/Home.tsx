import { useEffect, useState } from "react";
import { Header } from "../components/Header";
import { PrimaryNavigation } from "../components/PrimaryNavigation";
import { HeroBanner } from "../components/HeroBanner";
import { QuickGuideSection } from "../components/QuickGuideSection";
import { Footer } from "../components/Footer";
import { LoadSessionState, type SessionState } from "../handlers/LoadSessionState";
import { SignOutAccount } from "../handlers/SignOutAccount";

export type HomeState = { "session_state": SessionState };
export type HomeProps = {};

export function Home(_props: HomeProps) {
  const [session, setSession] = useState<SessionState>({ authenticated: false, username: null });

  useEffect(() => {
    let cancelled = false;
    LoadSessionState({}).then((result) => {
      if (!cancelled) {
        setSession(result.session_state);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSignOut = async () => {
    const result = await SignOutAccount({});
    if (result.success) {
      setSession({ authenticated: false, username: null });
    }
  };

  return (
    <section data-ui-id="UI_000001" className="min-h-screen bg-white">
      <Header session={session} onSignOut={handleSignOut} />
      <PrimaryNavigation />
      <main>
        <HeroBanner />
        <QuickGuideSection />
      </main>
      <Footer />
    </section>
  );
}
