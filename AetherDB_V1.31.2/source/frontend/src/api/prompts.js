import { get, post, put } from "./client.js";

export const listPromptProfiles = () => get("/prompts/profiles");
export const getPromptProfile = (profileId) => get(`/prompts/profiles/${profileId}`);
export const createPromptProfile = (payload) => post("/prompts/profiles", payload);
export const updatePromptProfile = (profileId, payload) => put(`/prompts/profiles/${profileId}`, payload);
export const activatePromptProfile = (profileId) => post(`/prompts/profiles/${profileId}/activate`, {});
export const testPromptProfile = (payload) => post("/prompts/test", payload);
