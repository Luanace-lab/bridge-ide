(function(){
  const body = document.body;
  const stateKey = body.dataset.stateKey || 'buddy_design_default';
  const shell = document.querySelector('[data-layout]');
  const defaultState = {
    name: '',
    role: '',
    guidance: 'uebernehmen',
    workflows: [],
    railOpen: body.dataset.railDefault !== 'closed',
    activeTab: body.dataset.defaultTab || 'profile',
    openSection: body.dataset.defaultSection || 'profile',
    avatarMode: 'generated',
    avatarSrc: '',
    avatarName: '',
  };

  function loadState(){
    try{
      const parsed = JSON.parse(localStorage.getItem(stateKey) || '{}');
      return Object.assign({}, defaultState, parsed);
    }catch(_error){
      return Object.assign({}, defaultState);
    }
  }

  const state = loadState();

  function saveState(){
    localStorage.setItem(stateKey, JSON.stringify(state));
  }

  function initials(value){
    const raw = String(value || 'Buddy').trim();
    if(!raw) return 'B';
    const parts = raw.split(/\s+/).slice(0, 2);
    return parts.map(part => part.charAt(0).toUpperCase()).join('') || raw.charAt(0).toUpperCase();
  }

  function guidanceLabel(value){
    return {
      uebernehmen: 'Uebernehmen',
      begleiten: 'Begleiten',
      erklaeren: 'Erklaeren',
    }[value] || 'Uebernehmen';
  }

  function renderNames(){
    document.querySelectorAll('[data-name-output]').forEach(node => {
      node.textContent = state.name || node.dataset.fallback || 'Du + Buddy';
    });
    document.querySelectorAll('[data-role-output]').forEach(node => {
      node.textContent = state.role || node.dataset.fallback || 'Noch offen';
    });
    document.querySelectorAll('[data-guidance-output]').forEach(node => {
      node.textContent = guidanceLabel(state.guidance);
    });
    document.querySelectorAll('[data-name-input]').forEach(input => {
      if(document.activeElement !== input){
        input.value = state.name;
      }
    });
    document.querySelectorAll('[data-role-input]').forEach(input => {
      if(document.activeElement !== input){
        input.value = state.role;
      }
    });
  }

  function renderGuidance(){
    document.querySelectorAll('[data-guidance]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.guidance === state.guidance);
    });
  }

  function renderWorkflows(){
    document.querySelectorAll('[data-workflow-list]').forEach(list => {
      list.innerHTML = '';

      if(!state.workflows.length){
        const empty = document.createElement('div');
        empty.className = 'workflowItem';
        empty.innerHTML = '<span>Noch kein Workflow gesetzt.</span><strong>Start leer</strong>';
        list.appendChild(empty);
        return;
      }

      state.workflows.forEach((workflow, index) => {
        const item = document.createElement('div');
        item.className = 'workflowItem';
        item.innerHTML = '<div><strong></strong><span>Buddy kann daraus spaeter eine echte Automation machen.</span></div><button type="button" aria-label="Workflow entfernen">&times;</button>';
        item.querySelector('strong').textContent = workflow;
        item.querySelector('button').addEventListener('click', () => {
          state.workflows.splice(index, 1);
          render();
        });
        list.appendChild(item);
      });
    });
  }

  function renderTabs(){
    document.querySelectorAll('[data-tab-target]').forEach(button => {
      button.classList.toggle('is-active', button.dataset.tabTarget === state.activeTab);
    });
    document.querySelectorAll('[data-tab-pane]').forEach(pane => {
      pane.classList.toggle('is-active', pane.dataset.tabPane === state.activeTab);
    });
  }

  function renderSections(){
    document.querySelectorAll('[data-section]').forEach(item => {
      item.classList.toggle('is-open', item.dataset.section === state.openSection);
    });
  }

  function renderRail(){
    const railOpen = state.railOpen !== false;
    body.classList.toggle('rail-hidden', !railOpen);
    if(shell){
      shell.classList.toggle('is-rail-hidden', !railOpen);
    }
    document.querySelectorAll('[data-rail-toggle]').forEach(button => {
      button.textContent = railOpen ? (button.dataset.labelClose || 'Rail ausblenden') : (button.dataset.labelOpen || 'Rail oeffnen');
      button.setAttribute('aria-expanded', railOpen ? 'true' : 'false');
    });
  }

  function renderAvatar(){
    document.querySelectorAll('[data-avatar-output]').forEach(node => {
      node.innerHTML = '';
      if(state.avatarMode === 'upload' && state.avatarSrc){
        const img = document.createElement('img');
        img.src = state.avatarSrc;
        img.alt = state.avatarName || 'Buddy';
        node.appendChild(img);
      } else {
        node.textContent = initials(state.name || 'Buddy');
      }
    });
  }

  function render(){
    renderNames();
    renderGuidance();
    renderWorkflows();
    renderTabs();
    renderSections();
    renderRail();
    renderAvatar();
    saveState();
  }

  document.querySelectorAll('[data-name-input]').forEach(input => {
    input.addEventListener('input', () => {
      state.name = String(input.value || '').trim();
      render();
    });
  });

  document.querySelectorAll('[data-role-input]').forEach(input => {
    input.addEventListener('input', () => {
      state.role = String(input.value || '').trim();
      render();
    });
  });

  document.querySelectorAll('[data-guidance]').forEach(button => {
    button.addEventListener('click', () => {
      state.guidance = button.dataset.guidance;
      render();
    });
  });

  document.querySelectorAll('[data-add-workflow]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.workflowInput || '');
      const raw = String(input ? input.value : '').trim();
      if(!raw) return;
      if(!state.workflows.includes(raw)){
        state.workflows.unshift(raw);
      }
      if(input){
        input.value = '';
      }
      render();
    });
  });

  document.querySelectorAll('[data-workflow-template]').forEach(button => {
    button.addEventListener('click', () => {
      const raw = button.dataset.workflowTemplate;
      if(!raw) return;
      if(!state.workflows.includes(raw)){
        state.workflows.unshift(raw);
      }
      render();
    });
  });

  document.querySelectorAll('[data-tab-target]').forEach(button => {
    button.addEventListener('click', () => {
      state.activeTab = button.dataset.tabTarget;
      render();
    });
  });

  document.querySelectorAll('[data-section-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      const next = button.dataset.sectionToggle;
      state.openSection = state.openSection === next ? '' : next;
      render();
    });
  });

  document.querySelectorAll('[data-rail-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      state.railOpen = state.railOpen === false;
      render();
    });
  });

  const showRail = document.getElementById('showRailBtn');
  if(showRail){
    showRail.addEventListener('click', () => {
      state.railOpen = true;
      render();
    });
  }

  document.querySelectorAll('[data-avatar-generate]').forEach(button => {
    button.addEventListener('click', () => {
      state.avatarMode = 'generated';
      state.avatarSrc = '';
      state.avatarName = '';
      render();
    });
  });

  document.querySelectorAll('[data-avatar-upload]').forEach(input => {
    input.addEventListener('change', event => {
      const file = event.target.files && event.target.files[0];
      if(!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        state.avatarMode = 'upload';
        state.avatarSrc = String(reader.result || '');
        state.avatarName = file.name;
        render();
      };
      reader.readAsDataURL(file);
      event.target.value = '';
    });
  });

  render();
})();
