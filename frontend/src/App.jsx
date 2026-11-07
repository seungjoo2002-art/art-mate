import { RouterProvider } from 'react-router-dom'
import AuthProvider from './app/providers/AuthProvider'
import { router } from './app/router'

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
