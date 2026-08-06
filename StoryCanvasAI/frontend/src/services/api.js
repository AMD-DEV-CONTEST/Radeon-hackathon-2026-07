import axios from "axios";

const api = axios.create({
    baseURL: "",
    timeout: 600000,
});

export const generateStory = async (prompt, pages) => {
    const response = await api.post("/generate", {
        prompt,
        pages,
    });

    return response.data;
};

export const getJobStatus = async (jobId) => {
    const response = await api.get(`/status/${jobId}`);
    return response.data;
};

export const getStory = async (jobId) => {
    const response = await api.get(`/story/${jobId}`);
    return response.data;
};

export default api;