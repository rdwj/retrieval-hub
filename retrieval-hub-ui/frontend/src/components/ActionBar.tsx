import { useNavigate } from 'react-router-dom';
import {
  Button,
  Flex,
  FlexItem,
  Tooltip,
} from '@patternfly/react-core';
import {
  CopyIcon,
  EnvelopeIcon,
  FlaskIcon,
  PencilAltIcon,
} from '@patternfly/react-icons';

import type { Source } from '../types/source';
import { defaultSamplePromptText } from '../utils/accessCheck';

interface ActionBarProps {
  source: Source;
  canQuery: boolean;
}

const MCP_CONFIG_TEMPLATE = (slug: string, mcpUrl?: string | null) => {
  const url = mcpUrl || 'https://mcp.retrieval-hub.example.com/mcp';
  return `{
  "mcpServers": {
    "retrieval-hub": {
      "type": "streamable-http",
      "url": "${url}"
    }
  }
}

Example query:
  retrieve({ "query": "your question here", "source": "${slug}", "top_k": 5 })`;
};

export default function ActionBar({ source, canQuery }: ActionBarProps) {
  const navigate = useNavigate();

  const copyMcp = async () => {
    const snippet = MCP_CONFIG_TEMPLATE(source.slug, (source as any).mcp_endpoint);
    try {
      await navigator.clipboard.writeText(snippet);
      alert('MCP config snippet copied to clipboard.');
    } catch {
      alert(`Clipboard unavailable. Snippet:\n\n${snippet}`);
    }
  };

  const copyPrompt = async () => {
    const text = defaultSamplePromptText(source);
    if (!text) {
      alert('No sample prompt is defined for this source.');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      alert('Sample prompt copied to clipboard.');
    } catch {
      alert(`Clipboard unavailable. Prompt:\n\n${text}`);
    }
  };

  const mailto = `mailto:${source.owner.contacts.join(',')}?subject=${encodeURIComponent(
    `Question about ${source.slug}`,
  )}&body=${encodeURIComponent(
    `Hi ${source.owner.team},\n\nI have a question about the retrieval-hub source "${source.name}" (slug: ${source.slug}):\n\n[ your question ]\n\nThanks.`,
  )}`;

  return (
    <Flex
      spaceItems={{ default: 'spaceItemsSm' }}
      style={{ marginBottom: '1rem' }}
    >
      <FlexItem>
        <Tooltip content={canQuery ? 'Open playground with this source' : 'You do not have query access to this source'}>
          <Button
            variant="primary"
            icon={<FlaskIcon />}
            isAriaDisabled={!canQuery}
            onClick={() => navigate(`/sources/${source.slug}/playground`)}
          >
            Test in Playground
          </Button>
        </Tooltip>
      </FlexItem>
      <FlexItem>
        <Button variant="secondary" icon={<CopyIcon />} onClick={copyMcp} data-tour-id="copy-mcp-config">
          Copy MCP Config
        </Button>
      </FlexItem>
      <FlexItem>
        <Button variant="secondary" icon={<PencilAltIcon />} onClick={copyPrompt}>
          Copy Sample Prompt
        </Button>
      </FlexItem>
      <FlexItem>
        <Button
          component="a"
          href={mailto}
          variant="secondary"
          icon={<EnvelopeIcon />}
          isAriaDisabled={source.owner.contacts.length === 0}
        >
          Contact Owner
        </Button>
      </FlexItem>
    </Flex>
  );
}
