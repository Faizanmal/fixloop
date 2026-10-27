import type { NextConfig } from "next";

const backendUrl =
  process.env.BACKEND_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // If backend is a remote host, configure rewrites so Vercel can proxy
    // requests server-side, preventing browser Mixed-Content (HTTPS->HTTP) blocking
    if (backendUrl && /^https?:\/\//i.test(backendUrl)) {
      const cleanBackend = backendUrl.replace(/\/+$/, "");
      return [
        {
          source: "/health",
          destination: `${cleanBackend}/health`,
        },
        {
          source: "/ready",
          destination: `${cleanBackend}/ready`,
        },
        {
          source: "/scenarios",
          destination: `${cleanBackend}/scenarios`,
        },
        {
          source: "/api/v1/:path*",
          destination: `${cleanBackend}/api/v1/:path*`,
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
