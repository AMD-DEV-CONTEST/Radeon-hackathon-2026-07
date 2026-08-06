import { get } from "./client.js";


export const getAuthStatus = () => get("/auth/status");
