/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Use worker_threads instead of child_process forks for static generation,
  // which is more reliable in sandboxed/restricted-spawn environments.
  experimental: {
    workerThreads: true,
  },
};

export default nextConfig;
