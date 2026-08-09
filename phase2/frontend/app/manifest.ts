import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Drug Detective",
    short_name: "Drug Detective",
    description:
      "Evidence-based drug repurposing research with ranked candidates and source citations.",
    start_url: "/",
    display: "standalone",
    background_color: "#050806",
    theme_color: "#26E03A",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
    ],
  };
}
