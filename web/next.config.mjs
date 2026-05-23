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

  // Memory-light production build for free-tier hosts (Render 512 MB).
  // We've already type-checked + linted in CI / locally before push, so
  // there's no value in re-doing it on the deploy server — and the type
  // checker is the biggest single memory consumer.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  // typedRoutes adds a build-time link-validation pass over every route;
  // useful in dev, not worth ~150 MB during the deploy build.
  // (re-enable locally by exporting NEXT_EXPERIMENTAL_TYPED_ROUTES=1)
  experimental: {},

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.INTERNAL_API_BASE || "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
