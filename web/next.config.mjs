/** @type {import('next').NextConfig} */
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // HSTS is set by the Ingress in production.
];

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    typedRoutes: true,
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    // In `next dev` (port 3000) forward /api/* to the FastAPI dev server on
    // port 8000 so the hybrid dev loop works without Caddy in front. In prod
    // the Ingress strips /api before forwarding.
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.INTERNAL_API_BASE || "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
