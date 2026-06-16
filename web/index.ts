import { SmilePlus } from 'lucide-vue-next'
import Stickers from './views/Stickers.vue'

export default {
    routes: [
        { path: 'stickers', component: Stickers }
    ],
    menus: [
        { path: '/stickers', label: '表情包池', icon: SmilePlus }
    ]
}
