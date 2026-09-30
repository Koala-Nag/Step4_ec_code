/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 画像は開発中バックエンドが配る。本番は Blob（設計 2.1）
  images: { unoptimized: true },
  // ★商品画像の取り込み（F-703）は Server Action 経由で送る。上限 5MB（N-36）＋base64 の膨らみぶん
  experimental: { serverActions: { bodySizeLimit: "8mb" } },
};
export default nextConfig;
