// SPDX-License-Identifier: GPL-3.0
/*
    Copyright 2021 0KIMS association.

    This file is generated with [snarkJS](https://github.com/iden3/snarkjs).

    snarkJS is a free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    snarkJS is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
    or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
    License for more details.

    You should have received a copy of the GNU General Public License
    along with snarkJS. If not, see <https://www.gnu.org/licenses/>.
*/

pragma solidity ^0.8.24;

contract VCPv3Groth16Verifier {
    // Scalar field size
    uint256 constant r    = 21888242871839275222246405745257275088548364400416034343698204186575808495617;
    // Base field size
    uint256 constant q   = 21888242871839275222246405745257275088696311157297823662689037894645226208583;

    // Verification Key data
    uint256 constant alphax  = 16428432848801857252194528405604668803277877773566238944394625302971855135431;
    uint256 constant alphay  = 16846502678714586896801519656441059708016666274385668027902869494772365009666;
    uint256 constant betax1  = 3182164110458002340215786955198810119980427837186618912744689678939861918171;
    uint256 constant betax2  = 16348171800823588416173124589066524623406261996681292662100840445103873053252;
    uint256 constant betay1  = 4920802715848186258981584729175884379674325733638798907835771393452862684714;
    uint256 constant betay2  = 19687132236965066906216944365591810874384658708175106803089633851114028275753;
    uint256 constant gammax1 = 11559732032986387107991004021392285783925812861821192530917403151452391805634;
    uint256 constant gammax2 = 10857046999023057135944570762232829481370756359578518086990519993285655852781;
    uint256 constant gammay1 = 4082367875863433681332203403145435568316851327593401208105741076214120093531;
    uint256 constant gammay2 = 8495653923123431417604973247489272438418190587263600148770280649306958101930;
    uint256 constant deltax1 = 18410320275638842372519135700955114107141636811359983094764571830298844557884;
    uint256 constant deltax2 = 12858658482279691679471255199802243287528595329722750699744068308672717220667;
    uint256 constant deltay1 = 17717868582157340469633961865800433702019677140364447198802855029629015491169;
    uint256 constant deltay2 = 16425483498003791257196880642804596743316076836345460988431493568614206964864;

    
    uint256 constant IC0x = 1015249663284496395859383779441929654327345550705216325224663726680402737158;
    uint256 constant IC0y = 4272440897435893443576383005638133009925549204516895286894324065257275901160;
    
    uint256 constant IC1x = 8364870055936132859380086027976282677256721596691703667859997038445281335656;
    uint256 constant IC1y = 13854475599945387409108916206822305477531696406067344868324376905254355800619;
    
    uint256 constant IC2x = 20904909719267502171781396027942574501288633909634473993033861258113267612646;
    uint256 constant IC2y = 21270471826304322147693093416065384217376285269358387655015871751466354518592;
    
    uint256 constant IC3x = 16301496321453938421756383287331169957289300546338136666117245084239346718622;
    uint256 constant IC3y = 12815309754673541705777488480565332510977702248950855082972402861178139261681;
    
    uint256 constant IC4x = 13016033622703281838978022621620364283417579714797486226085073662628482291766;
    uint256 constant IC4y = 6349101841004563220726731248191551389065513675972723850469461606750987112701;
    
    uint256 constant IC5x = 7849244811843703296590256641713896393392458556327578418580775569250627112992;
    uint256 constant IC5y = 9256153602981065662518980447590839100910306920806527293354713055231131294069;
    
    uint256 constant IC6x = 4155750057916602123139411934651379699249198369450375725349677264569258746665;
    uint256 constant IC6y = 4073259228955164895622142595713149002536462980444618442223923544565374479476;
    
    uint256 constant IC7x = 10838957553439646331712561311903402958482170333187785398678790487816036926973;
    uint256 constant IC7y = 5787465968108933837867069033055922605927334036420027803445534213999650900074;
    
    uint256 constant IC8x = 17286517950726195827373788731772403609646117311824977581702940078150436447624;
    uint256 constant IC8y = 16872762371334256820984731115946471033883050279576524446878167991858553155787;
    
    uint256 constant IC9x = 5437701827482169134795155896350533238901866526998432928803549199944972793575;
    uint256 constant IC9y = 4333689716215450483830896322304876038548856878887628846436283362369588477465;
    
    uint256 constant IC10x = 5961086140074168283933671798632191140491566892958975921099429081514578277920;
    uint256 constant IC10y = 15161119171497702729873739363089517082259221613781857146270471105127465697785;
    
    uint256 constant IC11x = 2536386277841216219370368892859054336052555928768193900689179127827959909720;
    uint256 constant IC11y = 10285369515920616412988607367895204711716165693851514962257843570677590777453;
    
    uint256 constant IC12x = 14463684148853206449713139642998578428193669291787431225024131254518387143827;
    uint256 constant IC12y = 16726879788034376840971271198131635894292817843271500319833572869823370968508;
    
    uint256 constant IC13x = 21783639013355381673206162587178251110317571823909839485589093027149733305970;
    uint256 constant IC13y = 14873988851531302068841553519287499694879540603274847322870272014916932813106;
    
    uint256 constant IC14x = 13345171933979015632914262398587881453040766443517596936700590005606097963580;
    uint256 constant IC14y = 6126232524865674779968830912259306081324524158058901731209700585965059760141;
    
    uint256 constant IC15x = 2840961335193874462948562447871509326576633041339806302933035791173805690936;
    uint256 constant IC15y = 3643086496859322498489162982891433086649906011707169310486201426683186691425;
    
    uint256 constant IC16x = 6141255257244653481397799805241508694666639801757543228821980435226718838126;
    uint256 constant IC16y = 4654080975425946954364897517513082098462614445875200170358389303171208651595;
    
    uint256 constant IC17x = 770265200194544364389509412507152717813685504612996332265602913933996427439;
    uint256 constant IC17y = 12168484476257718520178558369921268073283274795719459966997694031925307467660;
    
    uint256 constant IC18x = 8302541282196515145989504607533298827994489565141897591890834772480340029708;
    uint256 constant IC18y = 2714563159389404668997586767768847352156169069643642272716131419343453215602;
    
    uint256 constant IC19x = 3300569443341052524926007002038734417955304287724550417347831779082037575712;
    uint256 constant IC19y = 10436654534935466205679377453929282751057024217502171438452350226329448884429;
    
    uint256 constant IC20x = 5617739212028272853068321912015933943239816058811430238237379107957842048084;
    uint256 constant IC20y = 14403380360449864580253133624233016973329467783942058077849326114315394414333;
    
    uint256 constant IC21x = 20658598569788430785967335102619999262160479328822356444987887169116756592169;
    uint256 constant IC21y = 18588514184887397088495024044461889311086058353870556671404616266019553078359;
    
    uint256 constant IC22x = 12684871183095999337258048728156041062587267737696198014149185234474519460156;
    uint256 constant IC22y = 4839244931759720006784541923438138406192553344724356897342946259028449978161;
    
    uint256 constant IC23x = 17088477652907967187163189706073309952749337971726622310403875643639025118999;
    uint256 constant IC23y = 20991838829696040659792638363563037404165854048532063977302757392262903802238;
    
    uint256 constant IC24x = 15154509314798998620975254039393778993931275884655722185846299145150749932872;
    uint256 constant IC24y = 3604504154699948183740451730550256322511215461760897942183758215041134566257;
    
 
    // Memory data
    uint16 constant pVk = 0;
    uint16 constant pPairing = 128;

    uint16 constant pLastMem = 896;

    function verifyProof(uint[2] calldata _pA, uint[2][2] calldata _pB, uint[2] calldata _pC, uint[24] calldata _pubSignals) public view returns (bool) {
        assembly {
            function checkField(v) {
                if iszero(lt(v, r)) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }
            
            // G1 function to multiply a G1 value(x,y) to value in an address
            function g1_mulAccC(pR, x, y, s) {
                let success
                let mIn := mload(0x40)
                mstore(mIn, x)
                mstore(add(mIn, 32), y)
                mstore(add(mIn, 64), s)

                success := staticcall(sub(gas(), 2000), 7, mIn, 96, mIn, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }

                mstore(add(mIn, 64), mload(pR))
                mstore(add(mIn, 96), mload(add(pR, 32)))

                success := staticcall(sub(gas(), 2000), 6, mIn, 128, pR, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }

            function checkPairing(pA, pB, pC, pubSignals, pMem) -> isOk {
                let _pPairing := add(pMem, pPairing)
                let _pVk := add(pMem, pVk)

                mstore(_pVk, IC0x)
                mstore(add(_pVk, 32), IC0y)

                // Compute the linear combination vk_x
                
                g1_mulAccC(_pVk, IC1x, IC1y, calldataload(add(pubSignals, 0)))
                
                g1_mulAccC(_pVk, IC2x, IC2y, calldataload(add(pubSignals, 32)))
                
                g1_mulAccC(_pVk, IC3x, IC3y, calldataload(add(pubSignals, 64)))
                
                g1_mulAccC(_pVk, IC4x, IC4y, calldataload(add(pubSignals, 96)))
                
                g1_mulAccC(_pVk, IC5x, IC5y, calldataload(add(pubSignals, 128)))
                
                g1_mulAccC(_pVk, IC6x, IC6y, calldataload(add(pubSignals, 160)))
                
                g1_mulAccC(_pVk, IC7x, IC7y, calldataload(add(pubSignals, 192)))
                
                g1_mulAccC(_pVk, IC8x, IC8y, calldataload(add(pubSignals, 224)))
                
                g1_mulAccC(_pVk, IC9x, IC9y, calldataload(add(pubSignals, 256)))
                
                g1_mulAccC(_pVk, IC10x, IC10y, calldataload(add(pubSignals, 288)))
                
                g1_mulAccC(_pVk, IC11x, IC11y, calldataload(add(pubSignals, 320)))
                
                g1_mulAccC(_pVk, IC12x, IC12y, calldataload(add(pubSignals, 352)))
                
                g1_mulAccC(_pVk, IC13x, IC13y, calldataload(add(pubSignals, 384)))
                
                g1_mulAccC(_pVk, IC14x, IC14y, calldataload(add(pubSignals, 416)))
                
                g1_mulAccC(_pVk, IC15x, IC15y, calldataload(add(pubSignals, 448)))
                
                g1_mulAccC(_pVk, IC16x, IC16y, calldataload(add(pubSignals, 480)))
                
                g1_mulAccC(_pVk, IC17x, IC17y, calldataload(add(pubSignals, 512)))
                
                g1_mulAccC(_pVk, IC18x, IC18y, calldataload(add(pubSignals, 544)))
                
                g1_mulAccC(_pVk, IC19x, IC19y, calldataload(add(pubSignals, 576)))
                
                g1_mulAccC(_pVk, IC20x, IC20y, calldataload(add(pubSignals, 608)))
                
                g1_mulAccC(_pVk, IC21x, IC21y, calldataload(add(pubSignals, 640)))
                
                g1_mulAccC(_pVk, IC22x, IC22y, calldataload(add(pubSignals, 672)))
                
                g1_mulAccC(_pVk, IC23x, IC23y, calldataload(add(pubSignals, 704)))
                
                g1_mulAccC(_pVk, IC24x, IC24y, calldataload(add(pubSignals, 736)))
                

                // -A
                mstore(_pPairing, calldataload(pA))
                mstore(add(_pPairing, 32), mod(sub(q, calldataload(add(pA, 32))), q))

                // B
                mstore(add(_pPairing, 64), calldataload(pB))
                mstore(add(_pPairing, 96), calldataload(add(pB, 32)))
                mstore(add(_pPairing, 128), calldataload(add(pB, 64)))
                mstore(add(_pPairing, 160), calldataload(add(pB, 96)))

                // alpha1
                mstore(add(_pPairing, 192), alphax)
                mstore(add(_pPairing, 224), alphay)

                // beta2
                mstore(add(_pPairing, 256), betax1)
                mstore(add(_pPairing, 288), betax2)
                mstore(add(_pPairing, 320), betay1)
                mstore(add(_pPairing, 352), betay2)

                // vk_x
                mstore(add(_pPairing, 384), mload(add(pMem, pVk)))
                mstore(add(_pPairing, 416), mload(add(pMem, add(pVk, 32))))


                // gamma2
                mstore(add(_pPairing, 448), gammax1)
                mstore(add(_pPairing, 480), gammax2)
                mstore(add(_pPairing, 512), gammay1)
                mstore(add(_pPairing, 544), gammay2)

                // C
                mstore(add(_pPairing, 576), calldataload(pC))
                mstore(add(_pPairing, 608), calldataload(add(pC, 32)))

                // delta2
                mstore(add(_pPairing, 640), deltax1)
                mstore(add(_pPairing, 672), deltax2)
                mstore(add(_pPairing, 704), deltay1)
                mstore(add(_pPairing, 736), deltay2)


                let success := staticcall(sub(gas(), 2000), 8, _pPairing, 768, _pPairing, 0x20)

                isOk := and(success, mload(_pPairing))
            }

            let pMem := mload(0x40)
            mstore(0x40, add(pMem, pLastMem))

            // Validate that all evaluations ∈ F
            
            checkField(calldataload(add(_pubSignals, 0)))
            
            checkField(calldataload(add(_pubSignals, 32)))
            
            checkField(calldataload(add(_pubSignals, 64)))
            
            checkField(calldataload(add(_pubSignals, 96)))
            
            checkField(calldataload(add(_pubSignals, 128)))
            
            checkField(calldataload(add(_pubSignals, 160)))
            
            checkField(calldataload(add(_pubSignals, 192)))
            
            checkField(calldataload(add(_pubSignals, 224)))
            
            checkField(calldataload(add(_pubSignals, 256)))
            
            checkField(calldataload(add(_pubSignals, 288)))
            
            checkField(calldataload(add(_pubSignals, 320)))
            
            checkField(calldataload(add(_pubSignals, 352)))
            
            checkField(calldataload(add(_pubSignals, 384)))
            
            checkField(calldataload(add(_pubSignals, 416)))
            
            checkField(calldataload(add(_pubSignals, 448)))
            
            checkField(calldataload(add(_pubSignals, 480)))
            
            checkField(calldataload(add(_pubSignals, 512)))
            
            checkField(calldataload(add(_pubSignals, 544)))
            
            checkField(calldataload(add(_pubSignals, 576)))
            
            checkField(calldataload(add(_pubSignals, 608)))
            
            checkField(calldataload(add(_pubSignals, 640)))
            
            checkField(calldataload(add(_pubSignals, 672)))
            
            checkField(calldataload(add(_pubSignals, 704)))
            
            checkField(calldataload(add(_pubSignals, 736)))
            

            // Validate all evaluations
            let isValid := checkPairing(_pA, _pB, _pC, _pubSignals, pMem)

            mstore(0, isValid)
             return(0, 0x20)
         }
     }
 }
