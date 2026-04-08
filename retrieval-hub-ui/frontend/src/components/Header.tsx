import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Button,
  Dropdown,
  DropdownItem,
  DropdownList,
  Masthead,
  MastheadBrand,
  MastheadContent,
  MastheadMain,
  MenuToggle,
  Nav,
  NavItem,
  NavList,
  Toolbar,
  ToolbarContent,
  ToolbarGroup,
  ToolbarItem,
} from '@patternfly/react-core';
import { MoonIcon, SunIcon } from '@patternfly/react-icons';

import { usePersona } from '../context/PersonaContext';
import type { PersonaId } from '../types/source';

export default function Header() {
  const { persona, allPersonas, setPersonaId } = usePersona();
  const [personaOpen, setPersonaOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const location = useLocation();

  const isAdmin = persona.scopes.includes('admin.read');
  const isOwner = persona.owner_of_teams.length > 0;
  const canSeeAdmin = isAdmin || isOwner;

  const toggleDark = () => {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add('pf-v5-theme-dark');
    } else {
      document.documentElement.classList.remove('pf-v5-theme-dark');
    }
  };

  const onPersonaSelect = (id: PersonaId) => {
    setPersonaId(id);
    setPersonaOpen(false);
  };

  const activePath = location.pathname.startsWith('/admin')
    ? '/admin'
    : '/catalog';

  return (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <Link
            to="/catalog"
            style={{
              textDecoration: 'none',
              color: 'inherit',
              fontWeight: 700,
              fontSize: '1.25rem',
              letterSpacing: '0.02em',
            }}
          >
            retrieval-hub
            <span
              style={{
                fontSize: '0.75rem',
                marginLeft: '0.5rem',
                fontWeight: 400,
                opacity: 0.7,
              }}
            >
              stage-2 mockup
            </span>
          </Link>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <Nav aria-label="Primary" variant="horizontal">
                <NavList>
                  <NavItem
                    itemId="catalog"
                    isActive={activePath === '/catalog'}
                  >
                    <Link to="/catalog">Catalog</Link>
                  </NavItem>
                  {canSeeAdmin && (
                    <NavItem
                      itemId="admin"
                      isActive={activePath === '/admin'}
                    >
                      <Link to="/admin">Admin</Link>
                    </NavItem>
                  )}
                </NavList>
              </Nav>
            </ToolbarItem>
            <ToolbarGroup align={{ default: 'alignRight' }}>
              <ToolbarItem>
                <Button
                  variant="plain"
                  onClick={toggleDark}
                  aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
                >
                  {dark ? <SunIcon /> : <MoonIcon />}
                </Button>
              </ToolbarItem>
              <ToolbarItem>
                <Dropdown
                  isOpen={personaOpen}
                  onOpenChange={(open) => setPersonaOpen(open)}
                  toggle={(toggleRef) => (
                    <MenuToggle
                      ref={toggleRef}
                      onClick={() => setPersonaOpen(!personaOpen)}
                      isExpanded={personaOpen}
                    >
                      View as: {persona.display_name}
                    </MenuToggle>
                  )}
                >
                  <DropdownList>
                    {allPersonas.map((p) => (
                      <DropdownItem
                        key={p.id}
                        onClick={() => onPersonaSelect(p.id)}
                        isSelected={p.id === persona.id}
                      >
                        {p.display_name}
                      </DropdownItem>
                    ))}
                  </DropdownList>
                </Dropdown>
              </ToolbarItem>
            </ToolbarGroup>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );
}
