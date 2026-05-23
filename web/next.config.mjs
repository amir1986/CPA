/** @type {import('next').NextConfig} */
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  // No `output: 'standalone'`. Standalone runs a post-build `nft` trace +
  // file-copy step that peaks ~80 MB on top of the compile. We use
  // `next start` which doesn't need it.
  reactStrictMode: true,
  poweredByHeader: false,

  // Skip in-build lint/type-check (we run both in CI). Saves the biggest
  // single chunk of build memory on free-tier hosts.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  experimental: {},
  // Smaller build output.
  productionBrowserSourceMaps: false,

  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
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
