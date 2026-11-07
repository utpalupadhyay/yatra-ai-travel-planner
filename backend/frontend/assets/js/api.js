/**
 * Yatra AI — API Client
 * High-performance client with Server-Sent Events (SSE) streaming and JSON fallbacks.
 * Communicates with FastAPI backend. API key is NEVER exposed in client code.
 */

const API_BASE = (window.location.protocol === "file:" || window.location.port === "5500" || window.location.port === "3000")
  ? "http://localhost:8000/api/v1"
  : "/api/v1";

const API_ROOT = (window.location.protocol === "file:" || window.location.port === "5500" || window.location.port === "3000")
  ? "http://localhost:8000"
  : "";

const api = {

  /**
   * Stream trip itinerary generation in real-time (SSE).
   * @param {Object} payload - User trip preferences.
   * @param {Function} onChunk - (chunk, fullText) called as text arrives.
   * @param {Function} onDone - (finalResult) called upon stream completion.
   * @param {Function} onError - (error) called on failure.
   * @param {Function} onStart - called when first byte/header arrives.
   */
  async generateTripStream(payload, onChunk, onDone, onError, onStart) {
    const endpoint = `${API_ROOT}/api/generate-trip-stream`;

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 35000);

      const res = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!res.ok) {
        let errData = {};
        try { errData = await res.json(); } catch (_) {}
        const msg = errData.error || errData.detail || (
          res.status === 401 || res.status === 403
            ? "The AI API key is invalid or expired."
            : res.status === 429
            ? "The AI service is temporarily busy. Please try again."
            : `Server error (${res.status})`
        );
        throw new Error(msg);
      }

      if (onStart) onStart();

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let fullText = "";
      let finalData = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep last incomplete line

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data:")) continue;
          const jsonStr = trimmed.slice(5).trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            if (data.error) {
              throw new Error(data.error);
            }
            if (data.chunk) {
              fullText += data.chunk;
              if (onChunk) onChunk(data.chunk, fullText);
            }
            if (data.done) {
              finalData = data;
              if (data.itinerary) fullText = data.itinerary;
            }
          } catch (jsonErr) {
            if (jsonErr.message && jsonErr.message.includes("AI")) {
              throw jsonErr;
            }
          }
        }
      }

      if (onDone) {
        onDone({
          success: true,
          itinerary: fullText || (finalData && finalData.itinerary),
          interaction_id: finalData ? finalData.interaction_id : null,
          cached: finalData ? !!finalData.cached : false,
        });
      }
    } catch (err) {
      if (onError) onError(err);
      else throw err;
    }
  },

  /**
   * Standard JSON trip generation (fallback).
   */
  async generateTrip(payload) {
    const endpoint = `${API_ROOT}/api/generate-trip`;

    let res;
    try {
      res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (networkErr) {
      throw new Error("Unable to connect to the AI service. Please try again.");
    }

    let data;
    try {
      data = await res.json();
    } catch (parseErr) {
      throw new Error("The AI returned an unexpected response.");
    }

    if (!res.ok) {
      const errMsg = data.error || data.detail || (
        res.status === 401 || res.status === 403
          ? "The AI API key is invalid or expired."
          : res.status === 429
          ? "The AI service is temporarily busy. Please try again."
          : `Server error (${res.status})`
      );
      throw new Error(errMsg);
    }

    if (data.error) {
      throw new Error(data.error);
    }

    if (!data.itinerary) {
      throw new Error("The AI returned an unexpected response.");
    }

    return data;
  },

  /**
   * Stream chat assistant response (SSE).
   */
  async chatStream(payload, onChunk, onDone, onError) {
    const endpoint = `${API_ROOT}/api/chat-stream`;
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || `Server error: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let fullText = "";
      let finalData = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data:")) continue;
          const jsonStr = trimmed.slice(5).trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            if (data.error) throw new Error(data.error);
            if (data.chunk) {
              fullText += data.chunk;
              if (onChunk) onChunk(data.chunk, fullText);
            }
            if (data.done) {
              finalData = data;
              if (data.reply) fullText = data.reply;
            }
          } catch (jsonErr) {
            if (jsonErr.message && jsonErr.message.includes("AI")) throw jsonErr;
          }
        }
      }

      if (onDone) {
        onDone({
          success: true,
          reply: fullText || (finalData && finalData.reply),
          interaction_id: finalData ? finalData.interaction_id : null,
        });
      }
    } catch (err) {
      if (onError) onError(err);
      else throw err;
    }
  },

  async chat(payload) {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }
    return res.json();
  },

  async replanTripStream(payload, onChunk, onDone, onError) {
    const endpoint = `${API_ROOT}/api/trip/replan-stream`;
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || `Server error: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let fullText = "";
      let finalData = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data:")) continue;
          const jsonStr = trimmed.slice(5).trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);
            if (data.error) throw new Error(data.error);
            if (data.chunk) {
              fullText += data.chunk;
              if (onChunk) onChunk(data.chunk, fullText);
            }
            if (data.done) {
              finalData = data;
              if (data.itinerary) fullText = data.itinerary;
            }
          } catch (jsonErr) {
            if (jsonErr.message && jsonErr.message.includes("AI")) throw jsonErr;
          }
        }
      }

      if (onDone) {
        onDone({
          success: true,
          itinerary: fullText || (finalData && finalData.itinerary),
          interaction_id: finalData ? finalData.interaction_id : null,
        });
      }
    } catch (err) {
      if (onError) onError(err);
      else throw err;
    }
  },

  async replanTrip(payload) {
    const res = await fetch(`${API_BASE}/trip/replan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }
    return res.json();
  },

  async getPackingList(payload) {
    const res = await fetch(`${API_BASE}/trip/packing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }
    return res.json();
  },

  async optimizeBudget(params) {
    const url = new URL(`${API_BASE}/trip/optimize-budget`);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${res.status}`);
    }
    return res.json();
  },

  async healthCheck() {
    try {
      const res = await fetch(`${API_BASE}/health`);
      return res.ok;
    } catch {
      return false;
    }
  },
};
