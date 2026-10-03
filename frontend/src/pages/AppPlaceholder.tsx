import { Link } from "react-router-dom";
import { Logo } from "../components/site/Logo";

// The dashboard (signals feed, reasoning trace, portfolio, stress tests) is the next build step.
export default function AppPlaceholder() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 text-center">
      <Logo />
      <p className="text-mute">The dashboard is being built.</p>
      <Link to="/" className="text-sm text-gold hover:underline">
        ← Back to the site
      </Link>
    </div>
  );
}
