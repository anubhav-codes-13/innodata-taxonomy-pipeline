import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { ApiContext, type ApiClient } from "./lib/api";
import { mockApi } from "./lib/mockApi";
import { HttpApiClient } from "./lib/httpApi";
import { queryClient } from "./lib/queryClient";
import "./index.css";

// With VITE_API_BASE_URL set, the file endpoints hit the real FastAPI backend
// (HttpApiClient); downstream batch/document/history still use the in-memory
// simulator until those routes exist. Unset → fully mocked demo.
const apiBase = import.meta.env.VITE_API_BASE_URL;
const api: ApiClient = apiBase ? new HttpApiClient(apiBase, mockApi) : mockApi;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ApiContext.Provider value={api}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ApiContext.Provider>
  </React.StrictMode>,
);
