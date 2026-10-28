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
    // If backend is configured, proxy requests server-side through Next.js / Vercel
    // to prevent browser Mixed-Content (HTTPS frontend -> HTTP backend) blocking and CORS issues.
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
          source: "/investigations",
          destination: `${cleanBackend}/investigations`,
        },
        {
          source: "/investigations/:path*",
          destination: `${cleanBackend}/investigations/:path*`,
        },
        {
          source: "/api/:path*",
          destination: `${cleanBackend}/api/:path*`,
        },
        {
          source: "/docs",
          destination: `${cleanBackend}/docs`,
        },
        {
          source: "/openapi.json",
          destination: `${cleanBackend}/openapi.json`,
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
