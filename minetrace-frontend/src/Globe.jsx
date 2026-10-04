import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { useEffect, useMemo, useRef, useState } from 'react'
import { LEVELS } from './format.js'

// Textures load from /public/textures first, so the globe works offline.
// If they are missing (run `npm run textures` once), the online copy is used.
const TEXTURES = {
  earth: ['/textures/earth_atmos_2048.jpg', 'https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg'],
  clouds: ['/textures/earth_clouds_1024.png', 'https://threejs.org/examples/textures/planets/earth_clouds_1024.png']
}

function latLonToVector3(lat, lon, radius = 2.03) {
  const phi = (90 - lat) * (Math.PI / 180)
  const theta = (lon + 180) * (Math.PI / 180)

  return [
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta)
  ]
}

function useLocalFirstTexture([localUrl, remoteUrl]) {
  const [texture, setTexture] = useState(null)

  useEffect(() => {
    let cancelled = false
    const loader = new THREE.TextureLoader()
    const done = (loaded) => {
      if (cancelled) return
      loaded.colorSpace = THREE.SRGBColorSpace
      setTexture(loaded)
    }
    loader.load(localUrl, done, undefined, () => loader.load(remoteUrl, done, undefined, () => {}))
    return () => {
      cancelled = true
    }
  }, [localUrl, remoteUrl])

  return texture
}

function Marker({ country, isSelected }) {
  const position = useMemo(() => latLonToVector3(country.lat, country.lon, 2.045), [country.lat, country.lon])
  const groupRef = useRef()
  const { camera } = useThree()
  const worldPosition = useMemo(() => new THREE.Vector3(...position), [position])

  // Hide markers on the far side, and turn the ring to face the camera so it stays a circle
  useFrame(() => {
    if (!groupRef.current) return
    groupRef.current.visible = worldPosition.clone().normalize().dot(camera.position.clone().normalize()) > 0.06
    groupRef.current.quaternion.copy(camera.quaternion)
  })

  const color = isSelected ? '#ffffff' : '#3dffa0'

  return (
    <group ref={groupRef} position={position}>
      <mesh>
        <sphereGeometry args={[0.066, 20, 20]} />
        <meshBasicMaterial color={color} depthTest={false} />
      </mesh>
      <mesh>
        <ringGeometry args={[0.098, 0.126, 40]} />
        <meshBasicMaterial color={color} transparent opacity={isSelected ? 1 : 0.95} side={THREE.DoubleSide} depthTest={false} />
      </mesh>
    </group>
  )
}

/* Positions the country names (plain HTML, drawn in a layer over the canvas)
   every frame. Names on the back of the globe are hidden, names never leave the
   globe area, and names that would overlap another name are hidden until you
   zoom in. Names on the selected route always win. */
function LabelProjector({ countries, labelRefs, selected }) {
  const { camera, size } = useThree()
  const points = useMemo(
    () => countries.map((c) => ({ iso3: c.iso3, world: new THREE.Vector3(...latLonToVector3(c.lat, c.lon, 2.045)) })),
    [countries]
  )
  const scratch = useMemo(() => new THREE.Vector3(), [])
  const cameraDir = useMemo(() => new THREE.Vector3(), [])

  useFrame(() => {
    cameraDir.copy(camera.position).normalize()
    const onRoute = (iso3) => selected && (selected.from_iso === iso3 || selected.to_iso === iso3)
    const ordered = [...points].sort((a, b) => Number(onRoute(b.iso3)) - Number(onRoute(a.iso3)))
    const placed = []

    for (const point of ordered) {
      const el = labelRefs.current.get(point.iso3)
      if (!el) continue

      const facing = scratch.copy(point.world).normalize().dot(cameraDir) > 0.06
      if (!facing) {
        el.style.visibility = 'hidden'
        continue
      }

      scratch.copy(point.world).project(camera)
      const w = el.offsetWidth
      const h = el.offsetHeight
      let x = (scratch.x * 0.5 + 0.5) * size.width
      let y = (-scratch.y * 0.5 + 0.5) * size.height

      const isOnRoute = onRoute(point.iso3)
      y += isOnRoute ? (selected.from_iso === point.iso3 ? -32 : 32) : -21

      // keep inside the globe area
      x = Math.min(Math.max(x, w / 2 + 8), size.width - w / 2 - 8)
      y = Math.min(Math.max(y, h / 2 + 8), size.height - h / 2 - 8)

      const rect = { left: x - w / 2, right: x + w / 2, top: y - h / 2, bottom: y + h / 2 }
      const overlaps = placed.some((o) => rect.left < o.right + 3 && rect.right > o.left - 3 && rect.top < o.bottom + 2 && rect.bottom > o.top - 2)

      el.style.visibility = overlaps ? 'hidden' : 'visible'
      el.style.transform = `translate(${x - w / 2}px, ${y - h / 2}px)`
      if (!overlaps) placed.push(rect)
    }
  })

  return null
}

/* Smoothly turns the globe towards a selected route. Stops if the user drags. */
function CameraRig({ focus, controlsRef }) {
  const { camera } = useThree()
  const target = useRef(null)

  useEffect(() => {
    target.current = focus ? focus.clone().normalize() : null
  }, [focus])

  useEffect(() => {
    const controls = controlsRef.current
    if (!controls) return
    const cancel = () => {
      target.current = null
    }
    controls.addEventListener('start', cancel)
    return () => controls.removeEventListener('start', cancel)
  }, [controlsRef])

  useFrame(() => {
    if (!target.current) return
    const distance = camera.position.length()
    const desired = target.current.clone().multiplyScalar(distance)
    camera.position.lerp(desired, 0.08).setLength(distance)
    camera.lookAt(0, 0, 0)
    if (camera.position.clone().normalize().angleTo(target.current) < 0.01) target.current = null
  })

  return null
}

function TradeParticle({ curve, offset, selected, investigating }) {
  const particle = useMemo(
    () =>
      new THREE.Mesh(
        new THREE.SphereGeometry(0.026, 12, 12),
        new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: selected ? 1 : investigating ? 0.3 : 0.85 })
      ),
    [selected, investigating]
  )

  useFrame((state) => {
    particle.position.copy(curve.getPoint((state.clock.getElapsedTime() * 0.12 + offset) % 1))
  })

  return <primitive object={particle} />
}

function TradeRoute({ start, end, route, onSelect, selected, investigating }) {
  const color = LEVELS[route.level]?.color || LEVELS.limited.color

  const curve = useMemo(() => {
    const a = new THREE.Vector3(...latLonToVector3(start.lat, start.lon, 2.08))
    const b = new THREE.Vector3(...latLonToVector3(end.lat, end.lon, 2.08))
    const mid = a.clone().add(b).normalize().multiplyScalar(a.distanceTo(b) > 2 ? 2.42 : 2.3)
    return new THREE.QuadraticBezierCurve3(a, mid, b)
  }, [start, end])

  const flagged = route.level === 'risk' || route.level === 'caution'
  const minor = route.level === 'minor'
  const lineGeometry = useMemo(
    () => new THREE.TubeGeometry(curve, 96, selected ? 0.012 : flagged ? 0.0095 : minor ? 0.004 : 0.0072, 8, false),
    [curve, selected, flagged, minor]
  )
  const glowGeometry = useMemo(() => new THREE.TubeGeometry(curve, 96, selected ? 0.03 : 0.02, 8, false), [curve, selected])
  const hitGeometry = useMemo(() => new THREE.TubeGeometry(curve, 96, 0.055, 6, false), [curve])

  const handleClick = (event) => {
    event.stopPropagation()
    onSelect(route)
  }

  return (
    <group>
      <mesh geometry={glowGeometry} raycast={() => null}>
        <meshBasicMaterial color={color} transparent opacity={selected ? 0.32 : investigating ? 0.05 : 0.16} depthTest={false} depthWrite={false} />
      </mesh>
      <mesh geometry={lineGeometry} onClick={handleClick}>
        <meshBasicMaterial
          color={color}
          transparent
          opacity={selected ? 1 : investigating ? 0.3 : minor ? 0.45 : 0.92}
          depthTest={false}
          depthWrite={false}
        />
      </mesh>
      <mesh geometry={hitGeometry} onClick={handleClick}>
        <meshBasicMaterial transparent opacity={0} depthTest={false} depthWrite={false} />
      </mesh>
      {!minor && [0, 0.33, 0.66].map((offset) => (
        <TradeParticle key={offset} curve={curve} offset={offset} selected={selected} investigating={investigating} />
      ))}
    </group>
  )
}

/* Glow that is strongest at the globe's edge and fades out (fresnel effect) */
const atmosphereMaterial = new THREE.ShaderMaterial({
  vertexShader: `
    varying vec3 vNormal;
    void main() {
      vNormal = normalize(normalMatrix * normal);
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    varying vec3 vNormal;
    void main() {
      float intensity = pow(0.62 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 3.0);
      gl_FragColor = vec4(0.38, 0.72, 1.0, 1.0) * intensity * 1.4;
    }
  `,
  side: THREE.BackSide,
  blending: THREE.AdditiveBlending,
  transparent: true,
  depthWrite: false
})

/* A light that follows the camera, so the side of the globe you look at is always lit */
function CameraLight() {
  const lightRef = useRef()
  const { camera } = useThree()
  useFrame(() => lightRef.current?.position.copy(camera.position))
  return <directionalLight ref={lightRef} intensity={2.2} />
}

function Earth({ routes, countries, onSelect, selected }) {
  const earthTexture = useLocalFirstTexture(TEXTURES.earth)
  const cloudsTexture = useLocalFirstTexture(TEXTURES.clouds)

  const byIso = useMemo(() => Object.fromEntries(countries.map((c) => [c.iso3, c])), [countries])
  const isSelected = (r) => selected && r.from_iso === selected.from_iso && r.to_iso === selected.to_iso

  return (
    <group>
      <mesh>
        <sphereGeometry args={[2, 64, 64]} />
        {earthTexture
          ? <meshStandardMaterial key="map" map={earthTexture} roughness={0.8} />
          : <meshStandardMaterial key="plain" color="#1f3a4d" roughness={0.9} />}
      </mesh>

      {cloudsTexture && (
        <mesh scale={[1.015, 1.015, 1.015]}>
          <sphereGeometry args={[2, 64, 64]} />
          <meshStandardMaterial map={cloudsTexture} transparent opacity={0.22} depthWrite={false} />
        </mesh>
      )}

      <mesh scale={[1.12, 1.12, 1.12]} raycast={() => null} material={atmosphereMaterial}>
        <sphereGeometry args={[2, 64, 64]} />
      </mesh>

      {countries.map((country) => (
        <Marker
          key={country.iso3}
          country={country}
          isSelected={Boolean(selected && (selected.from_iso === country.iso3 || selected.to_iso === country.iso3))}
        />
      ))}

      {routes.map((route) => {
        const start = byIso[route.from_iso]
        const end = byIso[route.to_iso]
        if (!start || !end) return null
        return (
          <TradeRoute
            key={`${route.from_iso}-${route.to_iso}`}
            start={start}
            end={end}
            route={route}
            onSelect={onSelect}
            selected={isSelected(route)}
            investigating={Boolean(selected)}
          />
        )
      })}
    </group>
  )
}

// The globe opens facing Africa, Europe and Asia, where most critical-mineral trade runs.
const START_CAMERA = latLonToVector3(12, 32, 6)

export default function Globe({ routes, countries, onSelect, selected }) {
  const labelRefs = useRef(new Map())
  const controlsRef = useRef(null)

  const focus = useMemo(() => {
    if (!selected) return null
    const byIso = Object.fromEntries(countries.map((c) => [c.iso3, c]))
    const a = byIso[selected.from_iso]
    const b = byIso[selected.to_iso]
    if (!a || !b) return null
    const va = new THREE.Vector3(...latLonToVector3(a.lat, a.lon, 1))
    const vb = new THREE.Vector3(...latLonToVector3(b.lat, b.lon, 1))
    const mid = va.clone().add(vb)
    return mid.lengthSq() > 0.05 ? mid : va
  }, [selected, countries])

  const onRoute = (iso3) => selected && (selected.from_iso === iso3 || selected.to_iso === iso3)

  return (
    <>
      <Canvas camera={{ position: START_CAMERA, fov: 45 }}>
        <ambientLight intensity={0.9} />
        <CameraLight />
        <Earth routes={routes} countries={countries} onSelect={onSelect} selected={selected} />
        <LabelProjector countries={countries} labelRefs={labelRefs} selected={selected} />
        <CameraRig focus={focus} controlsRef={controlsRef} />
        <OrbitControls
          ref={controlsRef}
          enablePan={false}
          rotateSpeed={1}
          zoomSpeed={0.8}
          enableDamping
          dampingFactor={0.08}
          minDistance={3}
          maxDistance={8}
        />
      </Canvas>

      <div className="label-layer" aria-hidden="true">
        {countries.map((c) => (
          <div
            key={c.iso3}
            ref={(el) => {
              if (el) labelRefs.current.set(c.iso3, el)
              else labelRefs.current.delete(c.iso3)
            }}
            className={[
              'country-label',
              onRoute(c.iso3) ? 'country-label-selected' : 'country-label-minor',
              selected && !onRoute(c.iso3) ? 'country-label-dim' : ''
            ].join(' ')}
            style={{ visibility: 'hidden' }}
          >
            {c.short_name}
          </div>
        ))}
      </div>
    </>
  )
}
