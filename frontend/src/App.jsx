import Home from "./pages/Home.jsx";
import TaskCreator from "./pages/TaskCreator.jsx";
import OKRCreator from "./pages/OKRCreator.jsx";
import MeetingCreator from "./pages/MeetingCreator.jsx";
import LogCreator from "./pages/LogCreator.jsx";

function normalizePath(pathname) {
  return decodeURIComponent(pathname).replace(/\/+$/, "") || "/";
}

export default function App() {
  const path = normalizePath(window.location.pathname);

  if (path === "/task-creator" || path === "/task creator") return <TaskCreator />;
  if (path === "/okr-creator" || path === "/okr creator") return <OKRCreator />;
  if (path === "/meeting-creator" || path === "/meeting creator") return <MeetingCreator />;
  if (path === "/log-creator" || path === "/log creator" || path === "/log") return <LogCreator />;
  return <Home />;
}
