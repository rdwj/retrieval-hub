/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

export interface TourStep {
  targetId: string;
  title: string;
  content: string;
  route?: string;
  tabKey?: string;
  position: 'top' | 'bottom' | 'left' | 'right';
}

const TOUR_STEPS: TourStep[] = [
  {
    targetId: 'catalog-gallery',
    title: 'The source catalog',
    content:
      'Every retrieval source in the platform, browsable and filterable. Each card shows the source family, eval scores, recipe summary, and access level at a glance.',
    route: '/catalog',
    position: 'top',
  },
  {
    targetId: 'catalog-search',
    title: 'Search and filter',
    content:
      'Find sources by name, description, or domain tags. Filter by family, access level, or whether a query rewriter is available.',
    route: '/catalog',
    position: 'bottom',
  },
  {
    targetId: 'source-card-clinical',
    title: 'Drill into a source',
    content:
      'Click any card for the full detail view. The VA Clinical Practice Guidelines source has the richest rewriter story — let’s look at it.',
    route: '/catalog',
    position: 'right',
  },
  {
    targetId: 'source-detail-tabs',
    title: 'Everything about a source',
    content:
      'Each source has tabs for its overview, recipe, evaluations, rewriter configuration, sample prompts, access policy, and data lineage.',
    route: '/sources/va-clinical-guidelines',
    position: 'bottom',
  },
  {
    targetId: 'eval-tab-content',
    title: 'Quality transparency',
    content:
      'Recall@5 and MRR scores for every LLM this source has been evaluated against. No black-box retrieval — you see the numbers before you wire a source into your agent.',
    route: '/sources/va-clinical-guidelines',
    tabKey: 'evaluations',
    position: 'top',
  },
  {
    targetId: 'rewriter-tab-content',
    title: 'Per-source query rewriting',
    content:
      'The rewriter translates lay language into corpus vocabulary before retrieval. "High blood pressure" becomes "hypertension," giving a +0.22 recall lift on patient-phrased questions.',
    route: '/sources/va-clinical-guidelines',
    tabKey: 'rewriter',
    position: 'top',
  },
  {
    targetId: 'copy-mcp-config',
    title: 'MCP-native access',
    content:
      "One button gives you the MCP server config snippet. Paste it into your agent's config, and retrieval-hub handles embedding, rewriting, and routing. No pipeline code needed.",
    route: '/sources/rh-product-docs',
    position: 'bottom',
  },
  {
    targetId: 'access-tab-content',
    title: 'Access control',
    content:
      'Some sources are restricted to specific identity groups. Group membership flows through to the agent via the MCP auth token — if the calling identity lacks access, the query is denied.',
    route: '/sources/clinical-notes-staging',
    tabKey: 'access',
    position: 'top',
  },
  {
    targetId: 'persona-switcher',
    title: 'Try different personas',
    content:
      'Use the persona switcher to see the catalog from different perspectives. An agent developer without group membership sees an access-required banner on restricted sources.',
    position: 'bottom',
  },
  {
    targetId: 'tour-trigger',
    title: "That's the tour!",
    content:
      'You can restart this tour anytime from this button. Explore the catalog, check eval scores, try the playground, and see how retrieval-hub turns artisanal RAG into a platform service.',
    position: 'bottom',
  },
];

interface TourContextValue {
  isActive: boolean;
  currentStep: number;
  totalSteps: number;
  stepDef: TourStep | null;
  start: () => void;
  next: () => void;
  back: () => void;
  skip: () => void;
}

const TourContext = createContext<TourContextValue | null>(null);

export function TourProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();

  const goToStep = useCallback(
    (index: number) => {
      const step = TOUR_STEPS[index];
      if (step?.route && step.route !== location.pathname) {
        navigate(step.route);
      }
      setStepIndex(index);
    },
    [navigate, location.pathname],
  );

  const start = useCallback(() => {
    setStepIndex(0);
    setActive(true);
    const first = TOUR_STEPS[0];
    if (first.route && first.route !== location.pathname) {
      navigate(first.route);
    }
  }, [navigate, location.pathname]);

  const next = useCallback(() => {
    if (stepIndex >= TOUR_STEPS.length - 1) {
      setActive(false);
      localStorage.setItem('rh-tour-dismissed', 'true');
      return;
    }
    goToStep(stepIndex + 1);
  }, [stepIndex, goToStep]);

  const back = useCallback(() => {
    if (stepIndex <= 0) return;
    goToStep(stepIndex - 1);
  }, [stepIndex, goToStep]);

  const skip = useCallback(() => {
    setActive(false);
    localStorage.setItem('rh-tour-dismissed', 'true');
  }, []);

  const value: TourContextValue = {
    isActive: active,
    currentStep: stepIndex,
    totalSteps: TOUR_STEPS.length,
    stepDef: active ? TOUR_STEPS[stepIndex] : null,
    start,
    next,
    back,
    skip,
  };

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>;
}

export function useTour(): TourContextValue {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error('useTour must be used inside TourProvider');
  return ctx;
}
