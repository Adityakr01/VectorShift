// frontend/src/integrations/hubspot.js
import React, { useEffect, useState } from "react";

/**
 * HubSpotIntegration component
 * - Connect HubSpot (redirects to backend authorize endpoint)
 * - Load Items (calls backend to list Contacts, Companies, Deals)
 *
 * Works in two modes:
 *  - Authenticated app: backend maps creds to user session; call /items without state.
 *  - Unauthenticated test: backend stores creds under state and app reads ?state= from URL.
 */

export default function HubSpotIntegration() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stateIdentifier, setStateIdentifier] = useState(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("state")) {
      setStateIdentifier(params.get("state"));
    }
  }, []);

  const startOAuth = () => {
    // backend will redirect to HubSpot
    window.location.href = "/api/integrations/authorize/hubspot";
  };

  const loadItems = async () => {
    setLoading(true);
    setError(null);
    try {
      let url = "/api/integrations/items/hubspot";
      if (stateIdentifier) {
        url += `?state=${encodeURIComponent(stateIdentifier)}`;
      }
      const resp = await fetch(url, { credentials: "include" });
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Failed to load items: ${resp.status} ${txt}`);
      }
      const data = await resp.json();
      setItems(data);
    } catch (err) {
      setError(err.message || String(err));
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 12, border: "1px solid #e6e6e6", borderRadius: 8, maxWidth: 900 }}>
      <h3>HubSpot Integration</h3>
      <p>Connect HubSpot to import Contacts, Companies and Deals.</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button onClick={startOAuth}>Connect HubSpot</button>
        <button onClick={loadItems} disabled={loading}>
          {loading ? "Loading…" : "Load Items"}
        </button>
      </div>

      {error && <div style={{ color: "red", marginBottom: 12 }}>{error}</div>}

      {items && items.length > 0 ? (
        <div>
          <h4>Items ({items.length})</h4>
          <ul style={{ listStyle: "none", paddingLeft: 0 }}>
            {items.map((it) => (
              <li key={it.id} style={{ marginBottom: 10, borderBottom: "1px dashed #eee", paddingBottom: 8 }}>
                <strong>{it.title}</strong>
                <pre style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{JSON.stringify(it.parameters, null, 2)}</pre>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div style={{ color: "#666" }}>{loading ? null : "No items loaded yet."}</div>
      )}
    </div>
  );
}
