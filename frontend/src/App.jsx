import ClaudeUsage from "./pages/ClaudeUsage.jsx";
import Home from "./pages/Home.jsx";
import MeetingCreator from "./pages/MeetingCreator.jsx";
import OKRCreator from "./pages/OKRCreator.jsx";
import TaskCreator from "./pages/TaskCreator.jsx";

function normalizePath(pathname) {
  return decodeURIComponent(pathname).replace(/\/+$/, "") || "/";
}

export default function App() {
  const path = normalizePath(window.location.pathname);

  if (path === "/task-creator") return <TaskCreator />;
  if (path === "/okr-creator") return <OKRCreator />;
  if (path === "/meeting-creator") return <MeetingCreator />;
  if (path === "/claude-usage") return <ClaudeUsage />;
  return <Home />;
}
