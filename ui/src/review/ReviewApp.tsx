// AP workspace shell (layout modelled on bill-pay tools): ⌘K search, sidebar, Bill Pay > Bills as the core.
// Flow: invoice arrives -> agents run in the background -> For approval -> For payment -> History.
import { ActionIcon, AppShell, Badge, Button, Group, Menu, NavLink, ScrollArea, Stack, Text, UnstyledButton } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Spotlight, spotlight, type SpotlightActionData } from "@mantine/spotlight";
import { IconBrain, IconBuildingStore, IconChartBar, IconFileInvoice, IconHome, IconPackage, IconPlus, IconSearch, IconShieldCheck, IconSparkles } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type { Case } from "../types/contracts";
import { ap } from "./api";
import { AppProvider, useApp } from "./context";
import { amount, PEOPLE, shortName, type Seat } from "./format";
import { Avatarish } from "./parts";
import BillPage from "./pages/BillPage";
import Bills from "./pages/Bills";
import Home from "./pages/Home";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Memory from "./pages/Memory";
import Purchasing from "./pages/Purchasing";
import Vendors from "./pages/Vendors";

export default function ReviewApp() {
  return <AppProvider><Shell /></AppProvider>;
}

function Shell() {
  const { route, go, bills, live, seat, setSeat, refresh, vendors } = useApp();
  const [fixtures, setFixtures] = useState<Case[]>([]);
  useEffect(() => { ap.fixtures().then(setFixtures).catch(() => {}); }, []);
  const [page] = route;
  const open = bills.filter((b) => !["paid", "rejected"].includes(b.stage)).length;
  const mine = bills.filter((b) => ["needs_review", "on_hold"].includes(b.stage) && b.needs === seat).length;
  const who = PEOPLE[seat];

  const simulate = async (f: Case) => {
    try {
      await ap.intake(f);
      refresh();
      notifications.show({ title: "Invoice received", color: "gray",
        message: `${shortName(vendors[f.vendor_id]?.name ?? f.vendor_id)} · ${f.documents[0]?.filename ?? f.id}. ReconAI is reconciling it in the background.` });
    } catch (e) { notifications.show({ color: "red", title: "Could not start", message: String(e) }); }
  };

  const actions: SpotlightActionData[] = [
    ...[["home", "Home"], ["bills", "Bills"], ["bills/approval", "Bills · For approval"], ["bills/payment", "Bills · For payment"],
      ["vendors", "Vendors"], ["purchasing", "Purchasing · POs & receipts"], ["memory", "Vendor memory"], ["reports", "Insights · Reports"], ["settings", "Policy"]].map(([p, l]) => ({ id: `p-${p}`, label: l, description: "Go to page", onClick: () => go(p) })),
    ...bills.map((b) => ({ id: b.case_id, label: `${shortName(b.vendor_name)} ${b.invoice_no ? `INV# ${b.invoice_no}` : b.case_id}`, description: `${amount(b.amount, b.currency)} · ${b.stage.replace("_", " ")}`, onClick: () => go(`bill/${b.case_id}`) })),
    ...Object.values(vendors).map((v) => ({ id: v.id, label: v.name, description: `Vendor · ${v.country} · ${v.email_domain}`, onClick: () => go(`vendors/${v.id}`) })),
  ];

  const nav = (p: string) => page === p || (p === "bills" && page === "bill");
  return (
    <AppShell header={{ height: 60 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { desktop: page === "bill", mobile: true } }} padding={page === "bill" ? 0 : "xl"}>
      <AppShell.Header px="md">
        <Group h="100%" justify="space-between" wrap="nowrap">
          <Group gap="lg" wrap="nowrap" w={240}>
            <Text fz={22} c="brand.7" style={{ fontFamily: "'Saira Stencil One'" }}>RECON-AI</Text>
          </Group>
          <UnstyledButton onClick={() => spotlight.open()} style={{ flex: 1, maxWidth: 760 }}>
            <Group gap="xs" px="sm" py={7} bg="gray.1" style={{ borderRadius: 8 }}>
              <IconSearch size={16} color="gray" /><Text fz="sm" c="dimmed" style={{ flex: 1 }}>Search bills, vendors, pages</Text>
              <Badge variant="default" size="sm">⌘K</Badge>
            </Group>
          </UnstyledButton>
          <Group gap="sm" wrap="nowrap">
            <Badge variant="dot" color={live ? "brand" : "gray"}>{live ? "Live" : "Offline"}</Badge>
            <Menu position="bottom-end" width={340}>
              <Menu.Target><ActionIcon variant="default" size="lg" aria-label="Simulate incoming invoice"><IconPlus size={18} /></ActionIcon></Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>Simulate an invoice arriving in ap@helixsilicon.com</Menu.Label>
                <ScrollArea.Autosize mah={420}>
                {fixtures.map((f) => (
                  <Menu.Item key={f.id} onClick={() => simulate(f)} rightSection={<Text fz="xs" c="dimmed">{f.documents[0]?.channel ?? ""}</Text>}>
                    <Text fz="sm">{shortName(vendors[f.vendor_id]?.name ?? f.vendor_id)} · {f.id}</Text>
                    <Text fz="xs" c="dimmed" truncate>{f.documents.map((d) => d.filename).join(", ")}</Text>
                  </Menu.Item>
                ))}
                </ScrollArea.Autosize>
              </Menu.Dropdown>
            </Menu>
            <Menu position="bottom-end" width={260}>
              <Menu.Target><UnstyledButton><Group gap={8}><Avatarish name={who.name} size={32} />
                <div><Text fz="sm" fw={500} lh={1.1}>{who.name}</Text><Text fz="xs" c="dimmed" lh={1.1}>{who.title}</Text></div></Group></UnstyledButton></Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>Sign in as (demo)</Menu.Label>
                {(Object.keys(PEOPLE) as Seat[]).map((k) => (
                  <Menu.Item key={k} onClick={() => setSeat(k)} leftSection={<Avatarish name={PEOPLE[k].name} size={22} />} rightSection={k === seat ? "✓" : null}>
                    {PEOPLE[k].name} · {PEOPLE[k].title}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm" bg="gray.0">
        <Stack gap={2} style={{ flex: 1 }}>
          <NavLink label="Home" leftSection={<IconHome size={17} />} active={nav("home")} onClick={() => go("home")}
            rightSection={mine ? <Badge size="sm" color="violet">{mine}</Badge> : null} />
          <NavLink label="Insights" leftSection={<IconChartBar size={17} />} active={nav("reports")} onClick={() => go("reports")} />
          <NavLink label="Bill Pay" leftSection={<IconFileInvoice size={17} />} defaultOpened childrenOffset={28} active={nav("bills")}>
            <NavLink label="Bills" active={nav("bills")} onClick={() => go("bills")} rightSection={<Badge size="sm" variant="light">{open}</Badge>} />
          </NavLink>
          <NavLink label="Vendors" leftSection={<IconBuildingStore size={17} />} active={nav("vendors")} onClick={() => go("vendors")} />
          <NavLink label="Purchasing" leftSection={<IconPackage size={17} />} active={nav("purchasing")} onClick={() => go("purchasing")} />
          <NavLink label="Memory" leftSection={<IconBrain size={17} />} active={nav("memory")} onClick={() => go("memory")} />
          <NavLink label="Policy" leftSection={<IconShieldCheck size={17} />} active={nav("settings")} onClick={() => go("settings")} />
        </Stack>
        <Button variant="subtle" justify="flex-start" leftSection={<IconSparkles size={17} />} color="dark"
          onClick={() => (page === "bill" ? go(`bill/${route[1]}/ask`) : spotlight.open())}>Ask ReconAI</Button>
      </AppShell.Navbar>

      <AppShell.Main bg={page === "bill" ? "white" : undefined}>
        {page === "bill" && route[1] ? <BillPage key={route[1]} id={route[1]} tab={route[2]} />
          : page === "bills" ? <Bills tab={route[1]} />
            : page === "vendors" ? <Vendors openId={route[1]} />
              : page === "memory" ? <Memory vendorId={route[1]} />
              : page === "purchasing" ? <Purchasing openPo={route[1]} />
              : page === "reports" ? <Reports />
                : page === "settings" ? <Settings />
                  : <Home />}
      </AppShell.Main>
      <Spotlight actions={actions} nothingFound="Nothing found" highlightQuery limit={12} shortcut={["mod + K"]}
        searchProps={{ leftSection: <IconSearch size={18} />, placeholder: "Search bills, vendors, pages…" }} />
    </AppShell>
  );
}
