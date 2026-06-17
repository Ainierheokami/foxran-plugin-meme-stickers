import { SmilePlus } from 'lucide-vue-next'
import Stickers from './views/Stickers.vue'

const plugin = {
    id: 'meme_stickers',
    routes: [
        { path: 'stickers', component: Stickers }
    ],
    menus: [
        { path: '/stickers', label: '表情包池', icon: SmilePlus }
    ]
}

if (typeof window !== 'undefined' && (window as any).Foxran) {
    (window as any).Foxran.registerPlugin(plugin)
}

export default plugin
