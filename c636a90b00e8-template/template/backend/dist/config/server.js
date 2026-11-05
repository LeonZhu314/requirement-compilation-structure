export function serverPort() {
    const value = process.env.PORT ?? "3000";
    const port = Number(value);
    if (!Number.isInteger(port) || port < 0 || port > 65535) {
        throw new Error("PORT must be an integer between 0 and 65535");
    }
    return port;
}
