/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { PERSONAS } from '../data/mockSources';
import type { Persona, PersonaId } from '../types/source';

interface PersonaContextValue {
  persona: Persona;
  personaId: PersonaId;
  allPersonas: Persona[];
  setPersonaId: (id: PersonaId) => void;
}

const PersonaContext = createContext<PersonaContextValue | undefined>(undefined);

interface PersonaProviderProps {
  children: ReactNode;
}

export function PersonaProvider({ children }: PersonaProviderProps) {
  // Default persona is Platform Admin. Not persisted — a refresh resets.
  const [personaId, setPersonaIdState] = useState<PersonaId>('platform_admin');

  const setPersonaId = useCallback((id: PersonaId) => {
    setPersonaIdState(id);
  }, []);

  const value = useMemo<PersonaContextValue>(() => {
    const persona = PERSONAS.find((p) => p.id === personaId) ?? PERSONAS[0];
    return {
      persona,
      personaId,
      allPersonas: PERSONAS,
      setPersonaId,
    };
  }, [personaId, setPersonaId]);

  return (
    <PersonaContext.Provider value={value}>{children}</PersonaContext.Provider>
  );
}

export function usePersona(): PersonaContextValue {
  const ctx = useContext(PersonaContext);
  if (!ctx) {
    throw new Error('usePersona must be used inside a PersonaProvider');
  }
  return ctx;
}
