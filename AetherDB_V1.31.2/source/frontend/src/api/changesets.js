import { get, post } from "./client.js";


export const getChangeSet = (changeSetId) => get(`/changesets/${changeSetId}`);
export const confirmChangeSet = (changeSetId) => (
  post(`/changesets/${changeSetId}/confirm`, {})
);
