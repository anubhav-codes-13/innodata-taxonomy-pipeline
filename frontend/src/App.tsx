import { Navigate, Route, Routes } from "react-router-dom";
import { UploadScreen } from "./screens/UploadScreen";
import { ConfirmScreen } from "./screens/ConfirmScreen";
import { ProcessingScreen } from "./screens/ProcessingScreen";
import { BatchResultsScreen } from "./screens/BatchResultsScreen";
import { DocumentScreen } from "./screens/DocumentScreen";
import { HistoryScreen } from "./screens/HistoryScreen";
import { DashboardScreen } from "./screens/DashboardScreen";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadScreen />} />
      <Route path="/confirm" element={<ConfirmScreen />} />
      <Route path="/batches/:batchId/processing" element={<ProcessingScreen />} />
      <Route path="/batches/:batchId/results" element={<BatchResultsScreen />} />
      <Route path="/documents/:documentId" element={<DocumentScreen />} />
      <Route path="/history" element={<HistoryScreen />} />
      <Route path="/dashboard" element={<DashboardScreen />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
