/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

  // Proxy /api/v1/* to the backend at runtime (server-side env var, no build-time baking needed)
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
