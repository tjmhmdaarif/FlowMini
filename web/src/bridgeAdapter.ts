// BridgeAPI in-process adapter for FlowMini React UI.
//
// This module provides React hooks that communicate with the Python
// BridgeAPI class (core/bridge_api.py) via pywebview's js_api mechanism.
//
// Key design points:
// - Zero-network: all communication is in-process via pywebview's built-in
//   JavaScript bridge. No localhost ports, no WebSocket servers, no external
//   services.
// - Works in development mode (python app.py) and when packaged with PyInstaller.
// - The BridgeAPI instance is exposed as window.pywebview.api when the window
//   is created with js_api=BridgeAPI (see app.py).
//
// Available "methods" that React can call (via callBridgeAPI()):
//   - get_status():     → returns {status, model, level, active, uptime}
//   - get_config():     → returns {language, stt_engine, stt_model, stt_device,
//                         cleanup_mode, style_preset, show_hud, ...}
//   - toggle_recording(): → toggles dictation recording
//   - set_setting(k,v): → sets a config value (stt_model, cleanup, style, translate, vad, language, mic_device)
//   - self_test():      → runs STT self-test
//   - refresh_stats():  → returns session telemetry
//   - undo():           → restores raw transcript
//
// The React side polls get_status() + get_config() every ~150ms to keep the UI
// in sync. Hotkeys (Ctrl+Alt+D / Ctrl+Alt+F) are handled by the Python
// global hotkey listener (keyboard/pynput) and also exposed as UI buttons.
//
// IMPORTANT: This adapter MUST be used in a pywebview window created with:
//   webview.create_window("FlowMini", html, js_api=bridge_api)
// Without js_api, the BridgeAPI methods will not be available and calls will
// fail gracefully (return null / console.warn).

import { useEffect, useRef } from "react";

/**
 * Call a BridgeAPI method and return its result.
 * The BridgeAPI methods are available as window.pywebview.api.{method}().
 *
 * @param method The BridgeAPI method name (without parentheses)
 * @param args Optional arguments array for the method
 * @returns The method's return value, or null if the bridge is not available
 */
function callBridgeAPI(method: string, args: any[] = []): any {
  // Access the pywebview window instance
  // In electron/desktop contexts, the window's global object has pywebview reference
  // In browser preview mode, pywebview won't be available — calls will gracefully fail
  const win: any = typeof window !== "undefined" ? window : null;
  if (!win || !win.pywebview) {
    // Bridge not available (e.g., running in plain browser)
    // Return a placeholder that the caller can check
    return null;
  }

  const api = win.pywebview.api;
  if (!api || typeof api[method] !== "function") {
    // console.debug(`BridgeAPI.${method}() not available yet`);
    return null;
  }

  try {
    const result = api[method](...args);
    // Some BridgeAPI methods return dicts synchronously, some return nothing.
    // We return whatever was returned; the caller handles the shape.
    return result;
  } catch (e) {
    // console.error(`BridgeAPI.${method}() error:`, e);
    return null;
  }
}

/**
 * Hook that polls the BridgeAPI for status + config updates.
 *
 * The hook runs a setInterval that calls:
 *   - get_status() every 150ms → dispatches {type: "status", status} and {type: "level", level}
 *   - get_config() once on first poll → dispatches settings patch
 *
 * Dispatches to the React reducer via the provided dispatch function.
 *
 * @param dispatch The React reducer dispatch function
 * @param deps Optional dependency array (re-run if status changes, etc.)
 * @returns An unsubscribe function (clears the interval on unmount)
 */
function useBridgePolling(dispatch: any, deps: any[] = []) {
  const pollRef = useRef<number | null>(null);
  const configFetchedRef = useRef<boolean>(false);

  useEffect(() => {
    // Initial fetch on mount
    const fetchState = async () => {
      try {
        // 1. Get current status
        const status = await callBridgeAPI("get_status");
        if (status && typeof status.status === "string") {
          dispatch({
            type: "status",
            status: status.status,
          });
          dispatch({
            type: "level",
            level: typeof status.level === "number" ? status.level : 0,
          });
          // Update connected state based on status
          dispatch({
            type: "connected",
            value: status.status !== "error" && status.status !== "idle",
          });
        }

        // 2. Get config on first poll only
        if (!configFetchedRef.current && status) {
          configFetchedRef.current = true;
          const cfg = await callBridgeAPI("get_config");
          if (cfg && typeof cfg === "object") {
            dispatch({
              type: "settings",
              patch: {
                language: cfg.language ?? "en-US",
                cleanup: cfg.cleanup_mode ?? "light",
                style: cfg.style_preset ?? "casual",
                translate: cfg.translate_to_english !== undefined ? cfg.translate_to_english : true,
                vad: cfg.vad_sensitivity !== undefined ? true : false,
                stt_model: cfg.stt_model ?? "large-v3-turbo",
                stt_device: cfg.stt_device ?? "auto",
                mic_device: cfg.mic_device ?? "",
              },
            });
          }
        }
      } catch (e) {
        // Bridge not ready yet — will retry on next interval tick
        // console.debug("BridgeAPI polling not ready yet:", e);
      }
    };

    // Run initial fetch
    fetchState();

    // Poll every 150ms for real-time updates
    pollRef.current = window.setInterval(fetchState, 150);

    return () => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, deps);

  // Cleanup on component unmount
  useEffect(() => {
    return () => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, []);
}

/**
 * Hook that initializes the BridgeAPI / AppCoreManager on mount.
 *
 * Calls BridgeAPI.initialize() which starts the AppCoreManager backend
 * (audio capture, Whisper model, hotkeys, system tray) if not already running.
 *
 * @param dispatch The React reducer dispatch function
 */
function useBridgeInitialize(dispatch: any) {
  useEffect(() => {
    const init = async () => {
      try {
        const result = await callBridgeAPI("initialize");
        if (result && result.status === "initialized") {
          dispatch({
            type: "connected",
            value: true,
          });
          dispatch({
            type: "status",
            status: "idle",
          });
          dispatch({
            type: "level",
            level: 0,
          });
          // console.debug("BridgeAPI initialized successfully");
        } else {
          // console.debug("BridgeAPI initialization result:", result);
        }
      } catch (e) {
        // console.error("BridgeAPI initialization error:", e);
      }
    };

    init();

    // No cleanup needed — the Python side handles shutdown on exit
  }, [dispatch]);
}

export { callBridgeAPI, useBridgePolling, useBridgeInitialize };