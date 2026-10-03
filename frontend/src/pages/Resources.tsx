import { ArrowRight, BookOpen, FileText, Layers, ScrollText, Tags, Workflow, type LucideIcon } from "lucide-react";
import { PageHero } from "../components/site/PageHero";
import { Reveal } from "../components/site/Reveal";
import { REPO } from "../components/site/Sections";

// Each card opens a real document in the repository.
const ITEMS: { tag: string; title: string; body: string; href: string; icon: LucideIcon; tone: string }[] = [
  {
    tag: "Case study",
    title: "From SEC filing to CET1: Western Alliance",
    body: "The recorded end-to-end output for one regional-bank liquidity filing, kept as a regression test.",
    href: `${REPO}/blob/main/tests/golden/western_alliance.json`,
    icon: FileText,
    tone: "from-[#3a2f1c]",
  },
  {
    tag: "Method",
    title: "Module B: from shock to capital",
    body: "Trigger tiers, sector and systemic scope, shock calibration, ECL stages, RWA and CET1 reconciliation.",
    href: `${REPO}/blob/main/docs/module_b.md`,
    icon: Workflow,
    tone: "from-[#2f2a20]",
  },
  {
    tag: "Governance",
    title: "The assumptions register",
    body: "28 documented assumptions for shocks, PD multipliers, tax and scenario calibration, each with its rationale.",
    href: `${REPO}/blob/main/config/assumptions_register.yaml`,
    icon: ScrollText,
    tone: "from-[#3b2219]",
  },
  {
    tag: "Model card",
    title: "Improvement log",
    body: "Every model change with before and after numbers, including the locked test and the experiments that failed.",
    href: `${REPO}/blob/main/docs/IMPROVEMENT_LOG.md`,
    icon: BookOpen,
    tone: "from-[#3a2f1c]",
  },
  {
    tag: "Data note",
    title: "Building a human-labelled event set",
    body: "The labelling guide behind 296 human-labelled financial events: classes, tie-breakers and exceptions.",
    href: `${REPO}/blob/main/docs/labeling_guide.md`,
    icon: Tags,
    tone: "from-[#2f2a20]",
  },
  {
    tag: "Disclosure",
    title: "How AI was used in this project",
    body: "Where LLM silver labels were used, how they were checked against people, and what was never automated.",
    href: `${REPO}/blob/main/docs/ai_usage.md`,
    icon: Layers,
    tone: "from-[#3b2219]",
  },
];

export default function Resources() {
  return (
    <>
      <PageHero
        eyebrow="Resources"
        lines={["Intelligence for", "risk leaders."]}
        lede="Method notes, model documentation and governance material behind every number Tripwire shows."
      />
      <section className="container-x py-20 md:py-28">
        <div className="grid gap-x-5 gap-y-14 sm:grid-cols-2 lg:grid-cols-3">
          {ITEMS.map((it, i) => {
            const Icon = it.icon;
            return (
              <Reveal key={it.title} delay={(i % 3) * 0.08}>
                <a href={it.href} target="_blank" rel="noreferrer" className="group block">
                  <div
                    className={`relative aspect-[16/10] overflow-hidden rounded-lg border border-line bg-gradient-to-br ${it.tone} to-ink-2 transition-colors group-hover:border-gold/50`}
                  >
                    <span className="absolute top-5 left-6 font-serif text-3xl text-bone/90">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <Icon className="absolute top-5 right-5 h-6 w-6 text-gold" strokeWidth={1.5} />
                    {/* lines that sweep in on hover */}
                    <div className="absolute inset-x-6 bottom-6 space-y-2">
                      {[0.9, 0.7, 0.5].map((w, j) => (
                        <div key={j} className="h-px bg-line">
                          <div
                            className="h-full origin-left scale-x-0 bg-gold/70 transition-transform duration-700 group-hover:scale-x-100"
                            style={{ width: `${w * 100}%`, transitionDelay: `${j * 90}ms` }}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                  <p className="eyebrow mt-6 text-gold">{it.tag}</p>
                  <h3 className="mt-3 text-[22px] leading-snug font-light text-bone transition-colors group-hover:text-gold">
                    {it.title}
                  </h3>
                  <p className="mt-3 text-sm leading-relaxed text-mute">{it.body}</p>
                  <span className="mt-5 inline-flex items-center gap-1.5 border-b border-gold/40 pb-0.5 text-sm text-bone">
                    Read resource <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </span>
                </a>
              </Reveal>
            );
          })}
        </div>
      </section>
    </>
  );
}
