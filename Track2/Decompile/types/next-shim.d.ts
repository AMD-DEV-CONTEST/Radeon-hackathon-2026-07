declare module "next" {
  export interface NextConfig { reactStrictMode?: boolean }
  export interface Metadata {
    title?: string;
    description?: string;
  }
}
