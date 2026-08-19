import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
  },
  build: {
    manifest: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("/react/") || id.includes("/react-dom/") || id.includes("/scheduler/")) {
            return "react-vendor";
          }
          if (id.includes("/react-router/") || id.includes("/react-router-dom/")) {
            return "router-vendor";
          }
          if (id.includes("/@emotion/")) return "emotion-vendor";
          if (id.includes("/@mui/x-date-pickers/")) return "mui-x-vendor";
          if (id.includes("/@mui/")) return "mui-vendor";
          if (id.includes("/@hello-pangea/dnd/")) return "dnd-vendor";
          return undefined;
        },
      },
    },
  },
});
