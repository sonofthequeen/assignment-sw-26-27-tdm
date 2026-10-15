import { Link, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { CreateTestPage } from "./pages/CreateTest";
import { Dashboard } from "./pages/Dashboard";
import { RunBrowser } from "./pages/RunBrowser";
import { RunDetailPage } from "./pages/RunDetail";
import { SetupSnapshotPage } from "./pages/SetupSnapshotPage";
import { TestDetailPage } from "./pages/TestDetail";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="runs" element={<RunBrowser />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="tests/new" element={<CreateTestPage />} />
        <Route path="tests/:testId" element={<TestDetailPage />} />
        <Route path="setups/:setupSnapshotId" element={<SetupSnapshotPage />} />
        <Route
          path="*"
          element={
            <div role="alert">
              <h1 className="text-xl font-semibold">Page not found</h1>
              <Link to="/" className="text-accent-700 underline">Go to the dashboard</Link>
            </div>
          }
        />
      </Route>
    </Routes>
  );
}
