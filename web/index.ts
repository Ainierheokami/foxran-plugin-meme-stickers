import { SmilePlus } from 'lucide-vue-next'
import Stickers from './views/Stickers.vue'
import ConfigEditor from './components/ConfigEditor.vue'

const plugin = {
    id: 'meme_stickers',
    routes: [
        { path: 'stickers', component: Stickers }
    ],
    menus: [
        { path: '/stickers', label: '表情包池', icon: SmilePlus }
    ],
    // Visual editor the host settings page shows for these config files.
    configEditors: [
        { files: ['meme_sticker.yaml', 'meme_sticker.yml'], title: '表情包设置', component: ConfigEditor }
    ]
}

if (typeof window !== 'undefined' && (window as any).Foxran) {
    (window as any).Foxran.registerPlugin(plugin)
}

export default plugin
