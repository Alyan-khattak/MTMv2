import type { NextConfig } from "next";

// Static export is served by FastAPI at "/"; in `next dev`, proxy API calls to it.
const nextConfig: NextConfig = { output: "export", images: { unoptimized: true } };
export default nextConfig;
