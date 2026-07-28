/** @type {import('next').NextConfig} */
const sharedNextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@yn-tools/ui"],
};

module.exports = { sharedNextConfig };
