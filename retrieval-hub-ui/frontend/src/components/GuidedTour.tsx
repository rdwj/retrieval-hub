import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  CardBody,
  CardFooter,
  CardTitle,
  Flex,
  FlexItem,
} from '@patternfly/react-core';

import { useTour, type TourStep } from '../context/TourContext';

const PADDING = 8;
const GAP = 16;
const CARD_WIDTH = 400;

function computePopoverPosition(
  rect: DOMRect,
  position: TourStep['position'],
  cardHeight: number,
): { top: number; left: number } {
  let top: number;
  let left: number;

  switch (position) {
    case 'bottom':
      top = rect.bottom + PADDING + GAP;
      left = rect.left + rect.width / 2 - CARD_WIDTH / 2;
      break;
    case 'top':
      top = rect.top - PADDING - GAP - cardHeight;
      left = rect.left + rect.width / 2 - CARD_WIDTH / 2;
      break;
    case 'right':
      top = rect.top + rect.height / 2 - cardHeight / 2;
      left = rect.right + PADDING + GAP;
      break;
    case 'left':
      top = rect.top + rect.height / 2 - cardHeight / 2;
      left = rect.left - PADDING - GAP - CARD_WIDTH;
      break;
  }

  top = Math.max(16, Math.min(top, window.innerHeight - cardHeight - 16));
  left = Math.max(16, Math.min(left, window.innerWidth - CARD_WIDTH - 16));
  return { top, left };
}

export default function GuidedTour() {
  const { isActive, currentStep, totalSteps, stepDef, next, back, skip } =
    useTour();
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [cardHeight, setCardHeight] = useState(200);

  const findTarget = useCallback(() => {
    if (!stepDef) return null;
    return document.querySelector<HTMLElement>(
      `[data-tour-id="${stepDef.targetId}"]`,
    );
  }, [stepDef]);

  useEffect(() => {
    if (!isActive || !stepDef) {
      setTargetRect(null);
      return;
    }

    let frame: number;
    let attempts = 0;

    const poll = () => {
      const el = findTarget();
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Small delay after scroll to let the browser settle
        frame = requestAnimationFrame(() => {
          frame = requestAnimationFrame(() => {
            setTargetRect(el.getBoundingClientRect());
          });
        });
      } else if (attempts < 60) {
        attempts++;
        frame = requestAnimationFrame(poll);
      } else {
        setTargetRect(null);
      }
    };

    // Wait a frame for navigation to render
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, [isActive, currentStep, stepDef, findTarget]);

  // Recalculate on resize/scroll
  useEffect(() => {
    if (!isActive) return;

    let ticking = false;
    const recalc = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const el = findTarget();
        if (el) setTargetRect(el.getBoundingClientRect());
        ticking = false;
      });
    };

    window.addEventListener('resize', recalc);
    window.addEventListener('scroll', recalc, true);
    return () => {
      window.removeEventListener('resize', recalc);
      window.removeEventListener('scroll', recalc, true);
    };
  }, [isActive, findTarget]);

  // Measure card height for positioning
  useEffect(() => {
    if (cardRef.current) {
      setCardHeight(cardRef.current.getBoundingClientRect().height);
    }
  }, [currentStep, targetRect]);

  if (!isActive || !stepDef) return null;

  const isDark = document.documentElement.classList.contains('pf-v5-theme-dark');
  const overlayAlpha = isDark ? 0.65 : 0.5;

  const popoverPos = targetRect
    ? computePopoverPosition(targetRect, stepDef.position, cardHeight)
    : {
        top: window.innerHeight / 2 - cardHeight / 2,
        left: window.innerWidth / 2 - CARD_WIDTH / 2,
      };

  return (
    <>
      {/* Backdrop — blocks clicks behind the tour */}
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 9997,
          background: 'transparent',
        }}
        onClick={(e) => e.stopPropagation()}
      />

      {/* Spotlight hole */}
      {targetRect && (
        <div
          style={{
            position: 'fixed',
            top: targetRect.top - PADDING,
            left: targetRect.left - PADDING,
            width: targetRect.width + 2 * PADDING,
            height: targetRect.height + 2 * PADDING,
            borderRadius: 8,
            boxShadow: `0 0 0 9999px rgba(0, 0, 0, ${overlayAlpha})`,
            zIndex: 9998,
            pointerEvents: 'none',
            transition: 'top 0.3s ease, left 0.3s ease, width 0.3s ease, height 0.3s ease',
          }}
        />
      )}

      {/* Fallback full overlay when no target found */}
      {!targetRect && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9998,
            background: `rgba(0, 0, 0, ${overlayAlpha})`,
          }}
        />
      )}

      {/* Popover card */}
      <Card
        ref={cardRef}
        style={{
          position: 'fixed',
          zIndex: 9999,
          maxWidth: CARD_WIDTH,
          width: CARD_WIDTH,
          top: popoverPos.top,
          left: popoverPos.left,
          boxShadow: 'var(--pf-v5-global--BoxShadow--lg)',
          transition: 'top 0.3s ease, left 0.3s ease',
        }}
      >
        <CardTitle
          style={{ fontWeight: 600, fontSize: '1.1rem' }}
        >
          {stepDef.title}
        </CardTitle>
        <CardBody style={{ fontSize: '0.9rem', lineHeight: 1.5 }}>
          {stepDef.content}
        </CardBody>
        <CardFooter>
          <Flex
            justifyContent={{ default: 'justifyContentSpaceBetween' }}
            alignItems={{ default: 'alignItemsCenter' }}
          >
            <FlexItem>
              <span
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--pf-v5-global--Color--200)',
                }}
              >
                Step {currentStep + 1} of {totalSteps}
              </span>
            </FlexItem>
            <FlexItem>
              <Flex spaceItems={{ default: 'spaceItemsSm' }}>
                <FlexItem>
                  <Button variant="link" onClick={skip} style={{ padding: 0 }}>
                    Skip tour
                  </Button>
                </FlexItem>
                {currentStep > 0 && (
                  <FlexItem>
                    <Button variant="secondary" onClick={back} size="sm">
                      Back
                    </Button>
                  </FlexItem>
                )}
                <FlexItem>
                  <Button variant="primary" onClick={next} size="sm">
                    {currentStep === totalSteps - 1 ? 'Finish' : 'Next'}
                  </Button>
                </FlexItem>
              </Flex>
            </FlexItem>
          </Flex>
        </CardFooter>
      </Card>
    </>
  );
}
