import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import { VApp } from 'vuetify/components/VApp'
import { VBtn } from 'vuetify/components/VBtn'
import { VChip } from 'vuetify/components/VChip'
import { VIcon } from 'vuetify/components/VIcon'
import { VTable } from 'vuetify/components/VTable'
import { VTextField } from 'vuetify/components/VTextField'
import { VSelect } from 'vuetify/components/VSelect'
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg'
import { fr } from 'vuetify/locale'

export function createUi() {
  return createVuetify({
    components: { VApp, VBtn, VChip, VIcon, VTable, VTextField, VSelect },
    icons: { defaultSet: 'mdi', aliases, sets: { mdi } },
    locale: { locale: 'fr', messages: { fr } },
    theme: {
      defaultTheme: 'kubemap',
      themes: {
        kubemap: { dark: false, colors: { background: '#f5f5fa', surface: '#ffffff', 'on-surface': '#242433', primary: '#326ce5', secondary: '#326ce5', accent: '#326ce5', success: '#18794e', warning: '#946200', error: '#c42b45' } },
        kubemapDark: { dark: true, colors: { background: '#14141c', surface: '#1e1e2a', 'on-surface': '#ededf5', primary: '#326ce5', secondary: '#8ab4ff', accent: '#8ab4ff', success: '#73d6a3', warning: '#f2c66d', error: '#ff8fa3' } },
      },
    },
    defaults: {
      VBtn: { rounded: 'lg', elevation: 0, style: 'text-transform: none; letter-spacing: 0; font-weight: 600' },
      VTextField: { density: 'compact', variant: 'outlined', hideDetails: 'auto', rounded: 'lg' },
      VSelect: { density: 'compact', variant: 'outlined', hideDetails: 'auto', rounded: 'lg' },
    },
  })
}
