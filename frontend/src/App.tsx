import { BrowserRouter, Route, Routes } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import { CaseProvider } from "./lib/live";
import SiteLayout from "./components/site/SiteLayout";
import Landing from "./pages/Landing";
import Product from "./pages/Product";
import HowItWorks from "./pages/HowItWorks";
import ModelTrust from "./pages/ModelTrust";
import Resources from "./pages/Resources";
import AppLayout from "./app/AppLayout";
import Signals from "./app/pages/Signals";
import SignalDetail from "./app/pages/SignalDetail";
import Portfolio from "./app/pages/Portfolio";
import Watchlist from "./app/pages/Watchlist";
import Trust from "./app/pages/Trust";
import Status from "./app/pages/Status";
import Analyze from "./app/pages/Analyze";

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <CaseProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<SiteLayout />}>
            <Route path="/" element={<Landing />} />
            <Route path="/product" element={<Product />} />
            <Route path="/how-it-works" element={<HowItWorks />} />
            <Route path="/model-trust" element={<ModelTrust />} />
            <Route path="/resources" element={<Resources />} />
          </Route>
          <Route path="/app" element={<AppLayout />}>
            <Route index element={<Signals />} />
            <Route path="signals/:id" element={<SignalDetail />} />
            <Route path="portfolio" element={<Portfolio />} />
            <Route path="stress" element={<Portfolio />} />
            <Route path="watchlist" element={<Watchlist />} />
            <Route path="model-trust" element={<Trust />} />
            <Route path="status" element={<Status />} />
            <Route path="analyze" element={<Analyze />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </CaseProvider>
    </MotionConfig>
  );
}
