import { useState } from 'react'
import { GraduationCap, House, Lock, Mail, Palette, Target, Timer, User } from 'lucide-react'
import TopBar from '../components/layout/TopBar'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  IconBox,
  Input,
  PageIntro,
  Toggle,
} from '../components/ui'
import styles from './UiPreviewPage.module.css'

/** 개발용 디자인 시스템 미리보기 (/dev/ui, 개발 서버에서만 열림) */
export default function UiPreviewPage() {
  const [checked, setChecked] = useState(true)
  const [toggled, setToggled] = useState(true)
  const [chip, setChip] = useState('전체')

  return (
    <>
      <TopBar title="UI 미리보기" step="dev" />
      <main className={styles.page}>
        <PageIntro
          eyebrow="WELCOME TO ART MATE"
          title={'어떤 목적으로\n이용하시나요?'}
          description="선택한 유형에 맞는 성장 경험을 준비해 드릴게요."
        />

        <Section title="Button">
          <Button withArrow>시작하기</Button>
          <Button withArrow disabled>
            다음
          </Button>
          <Button variant="dark" size="md">
            출석하기
          </Button>
        </Section>

        <Section title="Input">
          <Input label="이름 또는 닉네임" icon={User} placeholder="김서연" />
          <Input label="이메일" icon={Mail} type="email" placeholder="name@example.com" />
          <Input
            label="비밀번호"
            icon={Lock}
            type="password"
            placeholder="8자 이상 입력"
            error="8자 이상 입력해 주세요."
          />
          <Input label="소속 학원 (선택)" icon={House} placeholder="홍대입시미술학원" />
        </Section>

        <Section title="Card · IconBox · Badge">
          <Card className={styles.row}>
            <IconBox icon={Palette} size="lg" />
            <div>
              <Badge>오늘의 수업</Badge>
              <p className={styles.cardTitle}>일반 수업 모드</p>
              <p className={styles.cardSub}>단계별 사진과 선생님 피드백을 기록해요.</p>
            </div>
          </Card>
          <Card variant="dark" className={styles.row}>
            <IconBox icon={Timer} size="lg" />
            <div>
              <Badge variant="light">5시간</Badge>
              <p className={styles.cardTitle}>실기시험 모드</p>
            </div>
          </Card>
          <Card variant="soft">채색 전 소재 간 크기 관계를 먼저 확인해 보세요.</Card>
          <div className={styles.row}>
            <IconBox icon={GraduationCap} variant="dark" />
            <IconBox icon={Target} variant="muted" />
            <Badge variant="overlay">모의시험</Badge>
          </div>
        </Section>

        <Section title="Chip">
          <div className={styles.chips}>
            {['전체', '기초디자인', '모의시험'].map((label) => (
              <Chip key={label} selected={chip === label} onClick={() => setChip(label)}>
                {label}
              </Chip>
            ))}
          </div>
        </Section>

        <Section title="Checkbox · Toggle">
          <Checkbox checked={checked} onChange={setChecked}>
            서비스 이용약관과 개인정보 처리방침에 동의합니다.
          </Checkbox>
          <Toggle checked={toggled} onChange={setToggled} label="수업 및 과제 알림" />
        </Section>
      </main>
    </>
  )
}

function Section({ title, children }) {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {children}
    </section>
  )
}
