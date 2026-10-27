import { createApp } from 'vue'
import App from './App.vue'
import { createUi } from './plugins/vuetify.js'
import './style.css'

createApp(App).use(createUi()).mount('#app')
