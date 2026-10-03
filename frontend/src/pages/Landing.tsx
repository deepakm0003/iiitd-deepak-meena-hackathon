import { Hero } from "../components/site/Hero";
import { CaseBand, Features, HowItWorks, Mission, Proof, Sources, Trust } from "../components/site/Sections";

export default function Landing() {
  return (
    <>
      <Hero />
      <CaseBand />
      <Mission />
      <Features />
      <HowItWorks />
      <Proof />
      <Sources />
      <Trust />
    </>
  );
}
