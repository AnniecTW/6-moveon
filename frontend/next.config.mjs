
/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  allowedDevOrigins: ["192.168.154.6", "10.193.204.122", "localhost", "127.0.0.1"],
}

export default nextConfig
