import {
  BookIcon,
  CodeIcon,
  DatabaseIcon,
  FileAltIcon,
  ProjectDiagramIcon,
  ServerIcon,
  StethoscopeIcon,
} from '@patternfly/react-icons';
import type { SourceFamily } from '../types/source';

interface FamilyIconProps {
  family: SourceFamily;
  size?: 'sm' | 'md' | 'lg';
}

export default function FamilyIcon({ family, size = 'md' }: FamilyIconProps) {
  const style = {
    sm: { width: '0.9rem', height: '0.9rem' },
    md: { width: '1.1rem', height: '1.1rem' },
    lg: { width: '1.4rem', height: '1.4rem' },
  }[size];

  switch (family) {
    case 'document':
      return <BookIcon style={style} />;
    case 'clinical_document':
      return <StethoscopeIcon style={style} />;
    case 'code':
      return <CodeIcon style={style} />;
    case 'tabular':
      return <DatabaseIcon style={style} />;
    case 'graph':
      return <ProjectDiagramIcon style={style} />;
    case 'external':
      return <ServerIcon style={style} />;
    default:
      return <FileAltIcon style={style} />;
  }
}
