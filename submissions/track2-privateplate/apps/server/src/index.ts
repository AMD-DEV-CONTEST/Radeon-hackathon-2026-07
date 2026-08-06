import { listen } from "./app.js";

const port = Number(process.env.PORT ?? 8787);
const { server } = await listen(port);
console.log(`PrivatePlate server listening on http://127.0.0.1:${port}`);

function shutdown() {
  server.close(() => process.exit(0));
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
