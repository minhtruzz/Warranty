-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Feb 09, 2026 at 11:45 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `warranty`
--

-- --------------------------------------------------------

--
-- Table structure for table `orders`
--

CREATE TABLE `orders` (
  `id` int(11) NOT NULL,
  `bill_code` varchar(50) NOT NULL,
  `customer_name` varchar(255) NOT NULL,
  `customer_phone` varchar(20) NOT NULL,
  `customer_address` varchar(500) NOT NULL,
  `created_at` datetime DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `orders`
--

INSERT INTO `orders` (`id`, `bill_code`, `customer_name`, `customer_phone`, `customer_address`, `created_at`, `updated_at`) VALUES
(170, 'TT-000205', 'Anh Phụng - Đồng nai', '961405060', 'Ngã 2 Ông Đồn - Xuân Lộc - Đồng Nai', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(171, 'TT-000320', 'Công ty TrueValue - Đà Nẵng (COD)', '909296768', '33 ĐẶNG THAI MAI ,THANH KHÊ ,ĐÀ NẴNG', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(172, 'TT-000335', 'CH 24h Store - 652 Đường 3/2', '862612424', '652 Đường 3/2, TP. HCM', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(173, 'TT-000344', 'A.Đoàn -179', '908011361', '1063 đường 3/2', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(174, 'TT-000462', 'CH Thái Khải - Nha Trang', '905044440', 'Khánh Hòa, 0905 044 440', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(175, 'TT-000488', 'a.Khoa - Cần Thơ (VIP 1)', '907204466', 'Cần Thơ', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(176, 'TT-000566', 'Anh Huy - Công ty Kenmy', '1237168179', '493/79/5 CMT8, P.3, Quận 10 - 01237168179', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(177, 'TT-000572', 'Lê Văn Hoàng - Quy Nhơn', '918696070', 'Quy Nhơn-Bình Định', '2026-02-09 16:50:52', '2026-02-09 16:50:52'),
(178, 'TT-000585', 'A.Đức - Hà Tiên', '939529352', 'Hà Tiên', '2026-02-09 16:50:52', '2026-02-09 17:18:21'),
(179, 'TT-000179', 'A', '1', '', '2026-02-09 16:57:41', '2026-02-09 16:57:41'),
(180, 'TT-000180', 'B', '2', '', '2026-02-09 16:57:50', '2026-02-09 16:57:50'),
(181, 'TT-000181', 'C', '3', '', '2026-02-09 16:57:58', '2026-02-09 16:57:58'),
(182, 'TT-000182', 'D', '4', '', '2026-02-09 16:58:04', '2026-02-09 16:58:04');

-- --------------------------------------------------------

--
-- Table structure for table `products`
--

CREATE TABLE `products` (
  `id` int(11) NOT NULL,
  `product_code` varchar(100) NOT NULL,
  `product_name` varchar(255) NOT NULL,
  `info_warranty` varchar(500) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `products`
--

INSERT INTO `products` (`id`, `product_code`, `product_name`, `info_warranty`) VALUES
(40, 'QUICK-236', 'Quick 236', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(41, 'QUICK-936ESSD', 'Quick 936 ESD ', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(43, 'QUICK-TS1200A', 'Quick TS1200A', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(44, 'QUICK-Q8', 'Quick Q8', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(45, 'QUICK-2008', 'Quick 2008', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(46, 'QUICK-2008D+', 'Quick 2008D+', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(47, 'QUICK-859D+', 'Quick 859D+', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(48, 'SUGON-202', 'Sugon 202', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(49, 'SUGON-2020D', 'Quick 859D+', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(50, 'SUGON-8610DXPRO', 'Sugon 8610DXPro ', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(51, 'SUGON-8650PRO', 'Sugon 8650 Pro', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(52, 'SUGON-3005PM', 'Sugon 3005PM', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH'),
(53, 'SUNSHINE-P2PRO', 'Sunshine P2Pro', 'Bảo hành 12 tháng 1 đổi 1, bao test 30 ngày, mất QR, mất tem KHÔNG BẢO HÀNH');

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id` int(11) NOT NULL,
  `username` varchar(50) NOT NULL,
  `password` varchar(255) NOT NULL,
  `role` varchar(20) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `users`
--

INSERT INTO `users` (`id`, `username`, `password`, `role`) VALUES
(3, 'admin', 'scrypt:32768:8:1$sIc3aA4av9f0NDqk$1913cbc432fe58ff8c9140b5264a472cc3ac463f0a3746f1d853845daac6f48d503bd7977722e023937828de242b34547565d20faca3a2112ccdd675747adeea', 'admin'),
(5, 'user', 'scrypt:32768:8:1$CguYxF8tyLhpaRkI$c8fb71aa8e0199295df0cdd53d6cb0b1c74fd7c021530e52a4a62eef1da52502044b9af91b04ee122ec352c23f402bea4f670b80c8295adead5d5c652efd5cd3', 'user'),
(33, 'minhtruzz', 'scrypt:32768:8:1$wcP25k7hE6kcpcJY$887d86c8bca9491109dea872b88599f01ce13a8648f393a4ea39d76f21a2840b82f64e2912af9bf1e7ae58cac010c1c8e7808c8fb4276f4713be30a6140ffa8b', 'admin');

-- --------------------------------------------------------

--
-- Table structure for table `warranty_items`
--

CREATE TABLE `warranty_items` (
  `id` int(11) NOT NULL,
  `uuid` varchar(50) NOT NULL,
  `bill_id` int(11) NOT NULL,
  `product_id` int(11) NOT NULL,
  `warranty_months` int(11) NOT NULL,
  `activated_at` datetime DEFAULT NULL,
  `ma_bill` varchar(50) NOT NULL,
  `so_phieu` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `warranty_items`
--

INSERT INTO `warranty_items` (`id`, `uuid`, `bill_id`, `product_id`, `warranty_months`, `activated_at`, `ma_bill`, `so_phieu`) VALUES
(374, '30ec45be-3c94-4b2c-a489-07c03b1c1c4c', 178, 45, 12, '2026-02-09 16:51:01', '260209CIYW85', 'BL1'),
(375, 'b238f786-40ec-43dd-8de2-9e779dda2b96', 178, 47, 12, '2026-02-09 16:55:21', '2602099MMXIL', 'BL2'),
(376, '4f2583de-90df-4907-8385-3811f0383627', 178, 47, 12, '2026-02-09 16:55:21', '2602099MMXIL', 'BL2'),
(377, '3fa17e21-2cbc-4155-b7e8-8b059a446b83', 179, 45, 12, '2026-02-09 16:57:41', '260209HE2Z36', ''),
(378, '68db10de-6b57-4b9a-ad70-ac510fe75296', 180, 45, 12, '2026-02-09 16:57:50', '2602092AQD9R', ''),
(379, 'a322f0e0-d2e5-44fb-823e-65bf299154b8', 181, 40, 12, '2026-02-09 16:57:58', '260209IC7D8T', ''),
(380, 'a70a4b34-4b9e-4387-a4c5-42d5a83fd774', 182, 45, 12, '2026-02-09 16:58:04', '2602095BGJD7', ''),
(381, 'be1c014e-1bca-49cb-a87a-04ffbeeb0fd7', 178, 45, 12, '2026-02-09 17:15:08', '2602090TW6PX', 'BL10'),
(382, '4f6f1622-e6e9-4dd3-8f89-0b87e96228a6', 178, 44, 12, '2026-02-09 17:18:21', '260209ZAG1B0', 'BL11');

--
-- Indexes for dumped tables
--

--
-- Indexes for table `orders`
--
ALTER TABLE `orders`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `bill_code` (`bill_code`);

--
-- Indexes for table `products`
--
ALTER TABLE `products`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `users`
--
ALTER TABLE `users`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `username` (`username`);

--
-- Indexes for table `warranty_items`
--
ALTER TABLE `warranty_items`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uuid` (`uuid`),
  ADD KEY `bill_id` (`bill_id`),
  ADD KEY `product_id` (`product_id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `orders`
--
ALTER TABLE `orders`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=183;

--
-- AUTO_INCREMENT for table `products`
--
ALTER TABLE `products`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=58;

--
-- AUTO_INCREMENT for table `users`
--
ALTER TABLE `users`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=37;

--
-- AUTO_INCREMENT for table `warranty_items`
--
ALTER TABLE `warranty_items`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=383;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `warranty_items`
--
ALTER TABLE `warranty_items`
  ADD CONSTRAINT `warranty_items_ibfk_1` FOREIGN KEY (`bill_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `warranty_items_ibfk_2` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
