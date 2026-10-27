<script setup>
import { computed } from 'vue'
import { mdiServerNetwork, mdiServer, mdiFolderOutline, mdiCubeOutline, mdiWeb, mdiLanConnect, mdiDatabaseOutline, mdiApplicationOutline, mdiHelpCircleOutline } from '@mdi/js'

const props = defineProps({ data: { type: Object, required: true } })
defineEmits(['open', 'focus', 'blur'])
const types = {
  clusters: { label: 'Cluster', icon: mdiServerNetwork },
  nodes: { label: 'Nœud · machine', icon: mdiServer },
  namespaces: { label: 'Namespace · espace', icon: mdiFolderOutline },
  pods: { label: 'Pod · unité d’exécution', icon: mdiCubeOutline },
  hosts: { label: 'Hôte · adresse web', icon: mdiWeb },
  services: { label: 'Service · point d’accès', icon: mdiLanConnect },
  traefikservices: { label: 'Cible Traefik', icon: mdiLanConnect },
  deployments: { label: 'Application · Deployment', icon: mdiApplicationOutline },
  statefulsets: { label: 'Application · StatefulSet', icon: mdiApplicationOutline },
  daemonsets: { label: 'Application · DaemonSet', icon: mdiApplicationOutline },
  pvcs: { label: 'Volume · stockage', icon: mdiDatabaseOutline },
}
const type = computed(() => types[props.data.kind] ?? { label: props.data.kind, icon: mdiHelpCircleOutline })
const action = computed(() => props.data.kind === 'namespaces' ? (props.data.expanded ? 'Regrouper cet espace' : 'Déplier ses pods') : props.data.kind === 'clusters' ? 'Voir tout le cluster' : props.data.kind === 'hosts' || props.data.kind === 'traefikservices' ? 'Voir les routes' : 'Ouvrir les détails')
</script>

<template>
  <button class="infra-card nodrag" :class="[data.tone, 'infra-' + data.kind]" :aria-label="type.label + ' ' + data.name" @click.stop="$emit('open', data)" @focus="$emit('focus')" @blur="$emit('blur')">
    <span class="infra-kind"><VIcon :icon="type.icon" size="16" />{{ type.label }}</span>
    <strong>{{ data.name }}</strong>
    <span class="infra-detail">{{ data.detail }}</span>
    <span class="infra-action">{{ action }} <span aria-hidden="true">↗</span></span>
  </button>
</template>

<style>
.infra-card { display: flex; flex-direction: column; gap: 7px; width: 280px; height: 144px; padding: 12px 16px; border: 1px solid var(--line); border-top: 3px solid var(--accent); border-radius: var(--radius-element); background: var(--surface); color: var(--fg); text-align: left; }
.infra-card:hover, .infra-card:focus-visible { border-color: var(--accent); }
.infra-card.bad { border-top-color: var(--bad); }
.infra-card.ok { border-top-color: var(--ok); }
.infra-card.warn { border-top-color: var(--warn); }
.infra-card.infra-clusters { border-top-color: rgb(var(--color-accent-orange)); }
.infra-card.infra-nodes { width: 232px; }
.infra-card.infra-pods { width: 232px; height: 104px; padding: 10px 14px; gap: 5px; }
.infra-pods .infra-action { display: none; }
.infra-kind { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.infra-card strong { display: block; max-width: 100%; font-family: var(--mono); font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.infra-detail { color: var(--muted); font-size: 13px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.infra-action { margin-top: auto; font-size: 12px; color: var(--accent); }
</style>
