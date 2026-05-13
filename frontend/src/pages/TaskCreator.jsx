import LegacyToolPage from "./LegacyToolPage.jsx";
import taskHtml from "../legacy/task-creator.html?raw";

export default function TaskCreator() {
  return <LegacyToolPage html={taskHtml} title="XC Gradient — Weekly Task Creator" subtitle="Weekly Task Creator" />;
}
