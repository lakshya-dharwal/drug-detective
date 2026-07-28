import { ImageResponse } from "next/og";

// Branded social preview card (1200x630), rendered at build/edge. Two-color:
// black background, neon-green accent — matching the app.
export const runtime = "edge";
export const alt = "Drug Detective — find drug repurposing candidates for any disease";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          justifyContent: "center",
          background: "#000000",
          padding: "80px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 40 }}>
          <svg width="72" height="72" viewBox="0 0 24 24" fill="none">
            <circle cx="9" cy="9" r="2.1" fill="#26E03A" />
            <circle cx="15" cy="7" r="1.5" fill="#26E03A" opacity="0.6" />
            <line x1="9" y1="9" x2="15" y2="7" stroke="#26E03A" strokeWidth="1.2" />
            <circle cx="11" cy="12" r="5.6" stroke="#26E03A" strokeWidth="1.7" />
            <line x1="15.5" y1="16.5" x2="20" y2="21" stroke="#26E03A" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div style={{ display: "flex", fontSize: 52, fontWeight: 800 }}>
            <span style={{ color: "#ffffff" }}>Drug&nbsp;</span>
            <span style={{ color: "#26E03A" }}>Detective</span>
          </div>
        </div>
        <div style={{ color: "#ffffff", fontSize: 60, fontWeight: 700, lineHeight: 1.1, maxWidth: 900 }}>
          Find drug repurposing candidates for any disease
        </div>
        <div style={{ color: "#9ca3af", fontSize: 30, marginTop: 30 }}>
          Ranked drugs · real evidence from PubMed, openFDA & ClinicalTrials.gov · source-cited
        </div>
      </div>
    ),
    size
  );
}
